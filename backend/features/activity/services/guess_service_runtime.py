from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.guess_service_parsing import now, parse_deadline
from backend.features.activity.services.guess_service_queries import get_or_create_setting
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.features.points.services.points_service import change_points, get_balance
from backend.platform.db.schema.models.core import PointsAccount, PointsTransaction
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import GuessBet, GuessEvent
from backend.shared.services.base import ValidationError
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.ui.message_config_panel import WAITING_VALUE, format_completion_lines, summarize_text
from backend.shared.services.user_service import ensure_user


@dataclass(frozen=True)
class GuessSettlementPlan:
    winner_payouts: dict[int, int]
    rake_payouts: dict[int, int]
    banker_delta: int
    loser_total: int
    winner_count: int
    participant_count: int
    system_subsidy: int = 0


async def resolve_user_id(session: AsyncSession, raw: str) -> int | None:
    if raw.strip() == "清空":
        return None
    user_id = await PointsExtendedService.resolve_user_id(session, raw)
    if user_id is None:
        raise ValidationError("未找到该用户，请输入用户ID或已记录的用户名。")
    return user_id


async def create_event(session: AsyncSession, chat_id: int, creator_user_id: int, *, draft: dict) -> GuessEvent:
    await ModuleSettingsService.ensure(session, chat_id=chat_id, user_id=creator_user_id)
    await ensure_user(session, creator_user_id, None, first_name=None, last_name=None, language_code=None)
    banker_user_id = draft.get("banker_user_id")
    deadline_at = parse_deadline(str(draft.get("deadline_at")))
    if deadline_at <= now():
        raise ValidationError("截止时间必须晚于当前时间。")
    event = GuessEvent(
        chat_id=chat_id,
        creator_user_id=creator_user_id,
        title=str(draft.get("title") or "竞猜活动")[:128],
        cover_file_id=draft.get("cover_file_id"),
        description=draft.get("description"),
        mode="banker" if banker_user_id else "no_banker",
        banker_user_id=banker_user_id,
        public_pool=int(draft.get("public_pool") or 0),
        options_json=list(draft.get("options") or []),
        command_keyword=str(draft.get("command_keyword") or "竞猜")[:32],
        deadline_at=deadline_at,
        allow_repeat_bet=bool(draft.get("allow_repeat_bet", False)),
        status="running",
    )
    session.add(event)
    await session.flush()
    return event


def format_event_preview(draft: dict, *, toast: str | None = None) -> str:
    options = draft.get("options") or []
    option_text = f"已设置 {len(options)} 项" if options else WAITING_VALUE
    banker_text = f"庄家 {draft['banker_user_id']}" if draft.get("banker_user_id") else "无庄"
    cover_text = "已设置" if draft.get("cover_file_id") else WAITING_VALUE
    command_text = summarize_text(draft.get("command_keyword"), limit=32)
    deadline_text = summarize_text(draft.get("deadline_at"), limit=32)
    lines = [
        "⚽ 竞猜活动",
        "",
        f"📮 活动名字: {summarize_text(draft.get('title'), limit=48)}",
        "",
        f"🏞️ 封面设置: {cover_text}",
        "",
        f"📋 活动说明: {summarize_text(draft.get('description'), limit=80)}",
        "",
        f"👾 本局庄家: {banker_text}",
        "",
        f"🧧 公共奖池: {int(draft.get('public_pool') or 0)}",
        "",
        f"📻 竞猜选项: {option_text}",
        "",
        f"🔎 群内指令: {command_text}",
        "",
        f"⏰ 截止时间: {deadline_text}",
        "",
        f"🔗 重复下注: {'允许' if draft.get('allow_repeat_bet') else '禁止'}",
    ]
    lines.extend(
        format_completion_lines(
            [
                ("活动名字", bool(str(draft.get("title") or "").strip())),
                ("竞猜选项", bool(options)),
                ("截止时间", bool(str(draft.get("deadline_at") or "").strip())),
            ],
            next_step="预览无误后发布到群",
            test_step=f"发布后在群里发送 `{command_text if command_text != WAITING_VALUE else '竞猜'} 选项 金额` 测试下注",
        )
    )
    if toast:
        lines = [toast, ""] + lines
    return "\n".join(lines)


def format_event_runtime(event: GuessEvent) -> str:
    options = "\n".join(f"{item['key']}：{item['label']}" for item in (event.options_json or []))
    status_map = {"running": "🟢 进行中", "pending": "🟡 待开奖", "opened": "✅ 已开奖", "cancelled": "❌ 已取消"}
    lines = [
        f"⚽ 竞猜：{event.title}",
        "",
        f"状态：{status_map.get(event.status, event.status)}",
        f"模式：{'👑 庄家模式' if event.mode == 'banker' else '🌍 无庄模式'}",
        f"公共奖池：{event.public_pool or 0}",
        f"截止时间：{event.deadline_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
        f"口令：{event.command_keyword}",
        "选项：",
        options,
    ]
    if event.description:
        lines.extend(["", event.description])
    if event.status == "running":
        lines.extend(["", f"发送 `{event.command_keyword}` 查看规则，发送 `{event.command_keyword} 选项 金额` 参与。"])
        if event.mode == "banker":
            lines.append("庄家模式：输家积分给庄家，庄家按 1:1 赔付赢家。")
        else:
            lines.append("无庄模式：赢家平分输家积分，非整除时向上取整。")
    if event.status == "opened" and event.winner_option:
        lines.extend(["", f"🏁 开奖结果：{event.winner_option}", "✅ 结算已完成，积分变动可在积分记录中核对。"])
    if event.status == "pending":
        lines.extend(["", "⏰ 已截止下注，请等待群内开奖结果。"])
    return "\n".join(lines)


async def place_bet(session: AsyncSession, *, event: GuessEvent, user_id: int, option_key: str, amount: int) -> GuessBet:
    if event.status != "running":
        raise ValidationError("当前活动已截止下注，请等待开奖。")
    if event.deadline_at <= now():
        raise ValidationError("当前活动已到截止时间，请等待系统关闭下注。")
    if amount <= 0:
        raise ValidationError("下注积分必须大于 0。")
    valid_options = {item["key"] for item in (event.options_json or [])}
    if option_key not in valid_options:
        raise ValidationError("竞猜选项不存在。")
    if not event.allow_repeat_bet:
        result = await session.execute(select(GuessBet).where(GuessBet.event_id == event.id, GuessBet.user_id == user_id))
        if result.scalar_one_or_none() is not None:
            raise ValidationError("当前活动不允许重复下注。")

    ok, _ = await change_points(session, event.chat_id, user_id, amount=-amount, txn_type=PointsTxnType.penalty.value, reason=f"竞猜下注 #{event.id}")
    if not ok:
        balance = await get_balance(session, event.chat_id, user_id)
        raise ValidationError(f"主积分不足，当前余额 {balance}。")
    bet = GuessBet(event_id=event.id, chat_id=event.chat_id, user_id=user_id, option_key=option_key, bet_points=amount)
    session.add(bet)
    await session.flush()
    return bet


async def settle_event(session: AsyncSession, *, event: GuessEvent, winner_option: str) -> str:
    if event.status not in {"pending", "running"}:
        raise ValidationError("当前活动状态不允许开奖。")
    options = {item["key"] for item in (event.options_json or [])}
    if winner_option not in options:
        raise ValidationError("开奖选项不存在。")
    result = await session.execute(select(GuessBet).where(GuessBet.event_id == event.id))
    bets = list(result.scalars().all())
    setting = await get_or_create_setting(session, event.chat_id)
    rake_ratio = _safe_rake_ratio(setting.rake_ratio)
    banker_user_id = event.banker_user_id if event.mode == "banker" else None
    plan = build_settlement_plan(
        bets,
        winner_option=winner_option,
        mode=event.mode,
        banker_user_id=banker_user_id,
        public_pool=int(event.public_pool or 0),
        rake_ratio=rake_ratio,
        rake_owner_user_id=setting.rake_owner_user_id,
    )

    for user_id, payout in plan.winner_payouts.items():
        if payout > 0:
            await change_points(session, event.chat_id, user_id, amount=payout, txn_type=PointsTxnType.reward.value, reason=f"竞猜中奖 #{event.id}")
    for user_id, rake_amount in plan.rake_payouts.items():
        if rake_amount > 0:
            await change_points(session, event.chat_id, user_id, amount=rake_amount, txn_type=PointsTxnType.reward.value, reason=f"竞猜抽水 #{event.id}")
    if banker_user_id is not None and plan.banker_delta != 0:
        await _apply_points_delta_allow_negative(session, event.chat_id, banker_user_id, amount=plan.banker_delta, reason=f"竞猜庄家结算 #{event.id}")

    event.status = "opened"
    event.winner_option = winner_option
    event.updated_at = now()
    await session.flush()
    notes = _format_settlement_notes(winner_option=winner_option, plan=plan, banker_user_id=banker_user_id)
    return "\n".join(notes)


def build_settlement_plan(
    bets: list[GuessBet],
    *,
    winner_option: str,
    mode: str,
    banker_user_id: int | None,
    public_pool: int,
    rake_ratio: Decimal,
    rake_owner_user_id: int | None,
) -> GuessSettlementPlan:
    winning_stakes = _stakes_by_user(bet for bet in bets if bet.option_key == winner_option)
    loser_total = sum(bet.bet_points for bet in bets if bet.option_key != winner_option)
    participant_count = len({bet.user_id for bet in bets})
    winner_count = len(winning_stakes)
    if winner_count == 0:
        return GuessSettlementPlan(
            winner_payouts={},
            rake_payouts={},
            banker_delta=loser_total if banker_user_id is not None else 0,
            loser_total=loser_total,
            winner_count=0,
            participant_count=participant_count,
        )

    if mode == "banker" and banker_user_id is not None:
        return _build_banker_settlement_plan(
            winning_stakes=winning_stakes,
            loser_total=loser_total,
            participant_count=participant_count,
            public_pool=public_pool,
            rake_ratio=rake_ratio,
        )

    return _build_no_banker_settlement_plan(
        winning_stakes=winning_stakes,
        loser_total=loser_total,
        participant_count=participant_count,
        public_pool=public_pool,
        rake_ratio=rake_ratio,
        rake_owner_user_id=rake_owner_user_id,
    )


def _build_no_banker_settlement_plan(
    *,
    winning_stakes: dict[int, int],
    loser_total: int,
    participant_count: int,
    public_pool: int,
    rake_ratio: Decimal,
    rake_owner_user_id: int | None,
) -> GuessSettlementPlan:
    winner_count = len(winning_stakes)
    split_pool = loser_total + max(public_pool, 0)
    share = _ceil_div(split_pool, winner_count)
    system_subsidy = max(share * winner_count - split_pool, 0)
    winner_payouts: dict[int, int] = {}
    rake_payouts: dict[int, int] = defaultdict(int)
    for user_id, stake in winning_stakes.items():
        rake = _rake_amount(share, rake_ratio)
        winner_payouts[user_id] = stake + share - rake
        if rake > 0 and rake_owner_user_id is not None:
            rake_payouts[rake_owner_user_id] += rake
    return GuessSettlementPlan(
        winner_payouts=winner_payouts,
        rake_payouts=dict(rake_payouts),
        banker_delta=0,
        loser_total=loser_total,
        winner_count=winner_count,
        participant_count=participant_count,
        system_subsidy=system_subsidy,
    )


def _build_banker_settlement_plan(
    *,
    winning_stakes: dict[int, int],
    loser_total: int,
    participant_count: int,
    public_pool: int,
    rake_ratio: Decimal,
) -> GuessSettlementPlan:
    winner_count = len(winning_stakes)
    public_share = _ceil_div(max(public_pool, 0), winner_count)
    winner_payouts: dict[int, int] = {}
    banker_delta = loser_total
    for user_id, stake in winning_stakes.items():
        winner_profit = stake + public_share
        rake = _rake_amount(winner_profit, rake_ratio)
        winner_payouts[user_id] = stake + winner_profit - rake
        banker_delta -= winner_profit - rake
    return GuessSettlementPlan(
        winner_payouts=winner_payouts,
        rake_payouts={},
        banker_delta=banker_delta,
        loser_total=loser_total,
        winner_count=winner_count,
        participant_count=participant_count,
        system_subsidy=0,
    )


def _stakes_by_user(bets) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for bet in bets:
        totals[int(bet.user_id)] += int(bet.bet_points)
    return dict(totals)


def _ceil_div(value: int, divisor: int) -> int:
    if value <= 0 or divisor <= 0:
        return 0
    return (value + divisor - 1) // divisor


def _rake_amount(amount: int, rake_ratio: Decimal) -> int:
    if amount <= 0 or rake_ratio <= 0:
        return 0
    return int((Decimal(amount) * rake_ratio).quantize(Decimal("1"), rounding=ROUND_DOWN))


def _safe_rake_ratio(value: str | None) -> Decimal:
    try:
        ratio = Decimal(value or "0")
    except (InvalidOperation, TypeError):
        return Decimal("0")
    if ratio < 0:
        return Decimal("0")
    if ratio > 1:
        return Decimal("1")
    return ratio


def _format_settlement_notes(*, winner_option: str, plan: GuessSettlementPlan, banker_user_id: int | None) -> list[str]:
    notes = [
        f"🏁 开奖结果：{winner_option}",
        f"参与人数：{plan.participant_count}",
        f"赢家人数：{plan.winner_count}",
        f"输方积分：{plan.loser_total}",
    ]
    if plan.winner_count == 0:
        notes.append("😔 本局无人猜中。")
    if plan.system_subsidy > 0:
        notes.append(f"系统兜底：{plan.system_subsidy}")
    rake_total = sum(plan.rake_payouts.values())
    if rake_total > 0:
        notes.append(f"抽水入账：{rake_total}")
    if banker_user_id is not None:
        notes.append(f"庄家结算：{plan.banker_delta:+d}")
    return notes


async def cancel_event(session: AsyncSession, *, event: GuessEvent) -> None:
    if event.status == "cancelled":
        return
    result = await session.execute(select(GuessBet).where(GuessBet.event_id == event.id))
    bets = list(result.scalars().all())
    for bet in bets:
        await change_points(session, event.chat_id, bet.user_id, amount=bet.bet_points, txn_type=PointsTxnType.reward.value, reason=f"竞猜取消退款 #{event.id}")
    event.status = "cancelled"
    event.updated_at = now()
    await session.flush()


async def _get_or_create_points_account(session: AsyncSession, chat_id: int, user_id: int) -> PointsAccount:
    result = await session.execute(select(PointsAccount).where(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id).with_for_update())
    account = result.scalar_one_or_none()
    if account is None:
        account = PointsAccount(chat_id=chat_id, user_id=user_id, balance=0)
        session.add(account)
        await session.flush()
    return account


async def _apply_points_delta_allow_negative(session: AsyncSession, chat_id: int, user_id: int, *, amount: int, reason: str) -> int:
    account = await _get_or_create_points_account(session, chat_id, user_id)
    account.balance += amount
    session.add(
        PointsTransaction(
            chat_id=chat_id,
            user_id=user_id,
            txn_type=PointsTxnType.reward.value if amount >= 0 else PointsTxnType.penalty.value,
            amount=amount,
            reason=reason,
        )
    )
    await session.flush()
    return account.balance
