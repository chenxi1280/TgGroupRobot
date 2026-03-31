from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount, PointsTransaction, TgUser
from bot.models.enums import PointsTxnType
from bot.models.expansion import GuessBet, GuessEvent, GuessSetting
from bot.services.activity.points_extended_service import PointsExtendedService
from bot.services.activity.points_service import change_points, get_balance
from bot.services.base import ValidationError
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.core.user_service import ensure_user


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def parse_ratio(raw: str) -> str:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError("抽水比例格式错误，请输入 0 到 1 之间的小数，例如 0.1。")
    if value < 0 or value > 1:
        raise ValidationError("抽水比例必须在 0 到 1 之间。")
    return format(value.normalize(), "f")


def parse_deadline(raw: str) -> dt.datetime:
    text = raw.strip()
    now = _now()
    if text.isdigit():
        minutes = int(text)
        if minutes <= 0:
            raise ValidationError("截止时间必须大于 0 分钟。")
        return now + dt.timedelta(minutes=minutes)
    try:
        target = dt.datetime.fromisoformat(text)
    except ValueError:
        pass
    else:
        if target.tzinfo is None:
            target = target.replace(tzinfo=dt.UTC)
        return target.astimezone(dt.UTC)
    if len(text) == 5 and ":" in text:
        hour, minute = map(int, text.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        return target
    raise ValidationError("截止时间格式错误，请输入分钟数或 HH:MM。")


def parse_options(raw: str) -> list[dict]:
    options: list[dict] = []
    for idx, line in enumerate([item.strip() for item in raw.splitlines() if item.strip()], start=1):
        if ":" in line:
            key, label = [part.strip() for part in line.split(":", 1)]
        else:
            key, label = str(idx), line
        if not key or not label:
            raise ValidationError("竞猜选项格式错误，请按 `编号:文案` 或每行一个文案输入。")
        options.append({"key": key[:16], "label": label[:32]})
    if len(options) < 2:
        raise ValidationError("至少需要 2 个竞猜选项。")
    return options


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> GuessSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(GuessSetting, chat_id)
    if setting is None:
        setting = GuessSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> GuessSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = _now()
    await session.flush()
    return setting


async def resolve_user_id(session: AsyncSession, raw: str) -> int | None:
    if raw.strip() == "清空":
        return None
    user_id = await PointsExtendedService.resolve_user_id(session, raw)
    if user_id is None:
        raise ValidationError("未找到该用户，请输入用户ID或已记录的用户名。")
    return user_id


async def create_event(session: AsyncSession, chat_id: int, creator_user_id: int, draft: dict) -> GuessEvent:
    await ModuleSettingsService.ensure(session, chat_id=chat_id, user_id=creator_user_id)
    await ensure_user(session, creator_user_id, None, None, None, None)
    event = GuessEvent(
        chat_id=chat_id,
        creator_user_id=creator_user_id,
        title=str(draft.get("title") or "竞猜活动")[:128],
        cover_file_id=draft.get("cover_file_id"),
        description=draft.get("description"),
        mode=str(draft.get("mode") or "no_banker"),
        banker_user_id=draft.get("banker_user_id"),
        public_pool=int(draft.get("public_pool") or 0),
        options_json=list(draft.get("options") or []),
        command_keyword=str(draft.get("command_keyword") or "竞猜")[:32],
        deadline_at=parse_deadline(str(draft.get("deadline_at"))),
        allow_repeat_bet=bool(draft.get("allow_repeat_bet", False)),
        status="running",
    )
    session.add(event)
    await session.flush()
    return event


async def count_events_by_status(session: AsyncSession, chat_id: int) -> dict[str, int]:
    result = await session.execute(
        select(GuessEvent.status, func.count(GuessEvent.id))
        .where(GuessEvent.chat_id == chat_id)
        .group_by(GuessEvent.status)
    )
    counts = {"pending": 0, "running": 0, "opened": 0, "cancelled": 0}
    for status, total in result.all():
        counts[str(status)] = int(total)
    return counts


async def list_events(session: AsyncSession, chat_id: int, status: str, limit: int = 10) -> list[GuessEvent]:
    stmt = (
        select(GuessEvent)
        .where(GuessEvent.chat_id == chat_id, GuessEvent.status == status)
        .order_by(desc(GuessEvent.id))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_event(session: AsyncSession, chat_id: int, event_id: int) -> GuessEvent | None:
    stmt = select(GuessEvent).where(GuessEvent.chat_id == chat_id, GuessEvent.id == event_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def format_event_preview(draft: dict) -> str:
    options = draft.get("options") or []
    option_text = "\n".join(f"- {item['key']}：{item['label']}" for item in options) if options else "未设置"
    return "\n".join(
        [
            "⚽ 竞猜 | 预览效果",
            "",
            f"活动名字：{draft.get('title') or '未设置'}",
            f"活动说明：{draft.get('description') or '未设置'}",
            f"庄家模式：{'👑 庄家模式' if draft.get('mode') == 'banker' else '🌍 无庄模式'}",
            f"本局庄家：{draft.get('banker_user_id') or '未设置'}",
            f"公共奖池：{draft.get('public_pool') or 0}",
            f"群内指令：{draft.get('command_keyword') or '竞猜'}",
            f"截止时间：{draft.get('deadline_at') or '未设置'}",
            f"下注限制：{'✅ 允许重复下注' if draft.get('allow_repeat_bet') else '❌ 单用户单次下注'}",
            "竞猜选项：",
            option_text,
        ]
    )


def format_event_runtime(event: GuessEvent) -> str:
    options = "\n".join(
        f"{item['key']}：{item['label']}"
        for item in (event.options_json or [])
    )
    status_map = {
        "running": "🟢 进行中",
        "pending": "🟡 待开奖",
        "opened": "✅ 已开奖",
        "cancelled": "❌ 已取消",
    }
    lines = [
        f"⚽ 竞猜：{event.title}",
        "",
        f"状态：{status_map.get(event.status, event.status)}",
        f"模式：{'👑 庄家模式' if event.mode == 'banker' else '🌍 无庄模式'}",
        f"截止时间：{event.deadline_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
        f"口令：{event.command_keyword}",
        "选项：",
        options,
    ]
    if event.description:
        lines.extend(["", event.description])
    if event.status == "running":
        lines.extend(["", f"发送 `{event.command_keyword}` 查看规则，发送 `{event.command_keyword} 选项 金额` 参与。"])
    if event.status == "opened" and event.winner_option:
        lines.extend(["", f"🏁 开奖结果：{event.winner_option}"])
    return "\n".join(lines)


async def get_running_event_by_keyword(session: AsyncSession, chat_id: int, keyword: str) -> GuessEvent | None:
    stmt = (
        select(GuessEvent)
        .where(GuessEvent.chat_id == chat_id, GuessEvent.command_keyword == keyword, GuessEvent.status.in_(["running", "pending"]))
        .order_by(desc(GuessEvent.id))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def place_bet(session: AsyncSession, *, event: GuessEvent, user_id: int, option_key: str, amount: int) -> GuessBet:
    if event.status != "running":
        raise ValidationError("当前活动已截止下注，请等待开奖。")
    if event.deadline_at <= _now():
        raise ValidationError("当前活动已到截止时间，请等待系统关闭下注。")
    if amount <= 0:
        raise ValidationError("下注积分必须大于 0。")
    valid_options = {item["key"] for item in (event.options_json or [])}
    if option_key not in valid_options:
        raise ValidationError("竞猜选项不存在。")
    if not event.allow_repeat_bet:
        stmt = select(GuessBet).where(GuessBet.event_id == event.id, GuessBet.user_id == user_id)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise ValidationError("当前活动不允许重复下注。")

    ok, _ = await change_points(
        session,
        event.chat_id,
        user_id,
        -amount,
        PointsTxnType.penalty.value,
        reason=f"竞猜下注 #{event.id}",
    )
    if not ok:
        balance = await get_balance(session, event.chat_id, user_id)
        raise ValidationError(f"主积分不足，当前余额 {balance}。")
    bet = GuessBet(
        event_id=event.id,
        chat_id=event.chat_id,
        user_id=user_id,
        option_key=option_key,
        bet_points=amount,
    )
    session.add(bet)
    await session.flush()
    return bet


async def close_due_events(session: AsyncSession) -> list[GuessEvent]:
    stmt = select(GuessEvent).where(GuessEvent.status == "running", GuessEvent.deadline_at <= _now())
    result = await session.execute(stmt)
    events = list(result.scalars().all())
    for event in events:
        event.status = "pending"
        event.updated_at = _now()
    await session.flush()
    return events


async def _get_or_create_points_account(session: AsyncSession, chat_id: int, user_id: int) -> PointsAccount:
    stmt = select(PointsAccount).where(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id).with_for_update()
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        account = PointsAccount(chat_id=chat_id, user_id=user_id, balance=0)
        session.add(account)
        await session.flush()
    return account


async def _apply_points_delta_allow_negative(session: AsyncSession, chat_id: int, user_id: int, amount: int, reason: str) -> int:
    account = await _get_or_create_points_account(session, chat_id, user_id)
    account.balance += amount
    session.add(PointsTransaction(
        chat_id=chat_id,
        user_id=user_id,
        txn_type=PointsTxnType.reward.value if amount >= 0 else PointsTxnType.penalty.value,
        amount=amount,
        reason=reason,
    ))
    await session.flush()
    return account.balance


async def settle_event(session: AsyncSession, *, event: GuessEvent, winner_option: str) -> str:
    if event.status not in {"pending", "running"}:
        raise ValidationError("当前活动状态不允许开奖。")
    options = {item["key"] for item in (event.options_json or [])}
    if winner_option not in options:
        raise ValidationError("开奖选项不存在。")
    stmt = select(GuessBet).where(GuessBet.event_id == event.id)
    result = await session.execute(stmt)
    bets = list(result.scalars().all())
    winners = [bet for bet in bets if bet.option_key == winner_option]
    losers = [bet for bet in bets if bet.option_key != winner_option]
    setting = await get_or_create_setting(session, event.chat_id)
    rake_ratio = Decimal(setting.rake_ratio or "0")
    rake_owner = setting.rake_owner_user_id

    winner_total = sum(item.bet_points for item in winners)
    loser_total = sum(item.bet_points for item in losers)
    public_pool = int(event.public_pool or 0)
    notes: list[str] = []

    if winners:
        if event.mode == "banker" and event.banker_user_id:
            banker_delta = loser_total
            for bet in winners:
                gross = bet.bet_points * 2 + (public_pool * bet.bet_points // winner_total if winner_total else 0)
                rake = int((Decimal(gross) * rake_ratio).quantize(Decimal("1"), rounding=ROUND_DOWN))
                payout = gross - rake
                await change_points(session, event.chat_id, bet.user_id, payout, PointsTxnType.reward.value, reason=f"竞猜中奖 #{event.id}")
                banker_delta -= payout
                if rake_owner:
                    await change_points(session, event.chat_id, rake_owner, rake, PointsTxnType.reward.value, reason=f"竞猜抽水 #{event.id}")
            await _apply_points_delta_allow_negative(session, event.chat_id, event.banker_user_id, banker_delta, f"竞猜庄家结算 #{event.id}")
        else:
            total_pool = loser_total + public_pool
            for bet in winners:
                share = total_pool * bet.bet_points // winner_total if winner_total else 0
                gross = bet.bet_points + share
                rake = int((Decimal(gross) * rake_ratio).quantize(Decimal("1"), rounding=ROUND_DOWN))
                payout = gross - rake
                await change_points(session, event.chat_id, bet.user_id, payout, PointsTxnType.reward.value, reason=f"竞猜中奖 #{event.id}")
                if rake_owner:
                    await change_points(session, event.chat_id, rake_owner, rake, PointsTxnType.reward.value, reason=f"竞猜抽水 #{event.id}")
    else:
        if event.mode == "banker" and event.banker_user_id:
            await _apply_points_delta_allow_negative(session, event.chat_id, event.banker_user_id, loser_total + public_pool, f"竞猜庄家流局 #{event.id}")
        notes.append("😔 本局无人猜中。")

    event.status = "opened"
    event.winner_option = winner_option
    event.updated_at = _now()
    await session.flush()
    notes.insert(0, f"🏁 开奖结果：{winner_option}")
    notes.append(f"参与人数：{len({bet.user_id for bet in bets})}")
    return "\n".join(notes)


async def cancel_event(session: AsyncSession, *, event: GuessEvent) -> None:
    if event.status == "cancelled":
        return
    result = await session.execute(select(GuessBet).where(GuessBet.event_id == event.id))
    bets = list(result.scalars().all())
    for bet in bets:
        await change_points(session, event.chat_id, bet.user_id, bet.bet_points, PointsTxnType.reward.value, reason=f"竞猜取消退款 #{event.id}")
    event.status = "cancelled"
    event.updated_at = _now()
    await session.flush()
