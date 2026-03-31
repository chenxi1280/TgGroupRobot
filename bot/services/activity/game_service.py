from __future__ import annotations

import datetime as dt
import random
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.expansion import GameParticipant, GameRound, GameSetting
from bot.models.core import TgUser
from bot.models.enums import PointsTxnType
from bot.services.activity.points_extended_service import PointsExtendedService
from bot.services.activity.points_service import change_points, get_balance
from bot.services.base import ValidationError
from bot.services.core.module_settings_service import ModuleSettingsService


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _format_ratio(value: str | None) -> str:
    return value or "未设置"


def parse_ratio(raw: str) -> str:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError("抽水比例格式错误，请输入 0 到 1 之间的小数，例如 0.1。")
    if value < 0 or value > 1:
        raise ValidationError("抽水比例必须在 0 到 1 之间。")
    normalized = value.normalize()
    return format(normalized, "f")


def validate_hhmm(raw: str) -> str:
    value = raw.strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValidationError("时间格式错误，请输入 HH:MM，例如 23:05。")
    return value


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> GameSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(GameSetting, chat_id)
    if setting is None:
        setting = GameSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> GameSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = _now()
    await session.flush()
    return setting


async def resolve_rake_owner(session: AsyncSession, raw: str) -> int | None:
    if raw.strip() == "清空":
        return None
    user_id = await PointsExtendedService.resolve_user_id(session, raw)
    if user_id is None:
        raise ValidationError("未找到该用户，请输入用户ID或已记录的用户名。")
    return user_id


async def get_rake_owner_label(session: AsyncSession, user_id: int | None) -> str:
    if user_id is None:
        return "未设置"
    user = await session.get(TgUser, user_id)
    if user is None:
        return str(user_id)
    if user.username:
        return f"@{user.username}"
    return user.first_name or str(user_id)


async def apply_auto_schedule(session: AsyncSession, now_local: dt.datetime) -> list[int]:
    stmt = select(GameSetting).where(GameSetting.auto_schedule_enabled.is_(True))
    result = await session.execute(stmt)
    settings = list(result.scalars().all())
    changed: list[int] = []
    hhmm = now_local.strftime("%H:%M")
    for setting in settings:
        touched = False
        if setting.auto_start_time and setting.auto_start_time == hhmm:
            if not setting.k3_enabled or not setting.blackjack_enabled:
                setting.k3_enabled = True
                setting.blackjack_enabled = True
                touched = True
        if setting.auto_stop_time and setting.auto_stop_time == hhmm:
            if setting.k3_enabled or setting.blackjack_enabled:
                setting.k3_enabled = False
                setting.blackjack_enabled = False
                touched = True
        if touched:
            setting.updated_at = _now()
            changed.append(setting.chat_id)
    await session.flush()
    return changed


def format_game_menu_text(chat_title: str, *, k3_enabled: bool, blackjack_enabled: bool, rake_ratio: str | None, rake_owner: str, auto_schedule_enabled: bool, auto_start_time: str | None, auto_stop_time: str | None, delete_mode: str) -> str:
    return "\n".join(
        [
            f"🎮 游戏 | {chat_title}",
            "",
            f"🎲 快3：{'✅ 启动' if k3_enabled else '❌ 关闭'}",
            f"🃏 黑杰克：{'✅ 启动' if blackjack_enabled else '❌ 关闭'}",
            f"💧 抽水比例：{_format_ratio(rake_ratio)}",
            f"👤 抽水归属：{rake_owner}",
            f"⏰ 定时启停：{'✅ 启动' if auto_schedule_enabled else '❌ 关闭'}",
            f"🕒 启动时间：{auto_start_time or '未设置'}",
            f"🌙 关停时间：{auto_stop_time or '未设置'}",
            f"🧹 删除游戏消息：{'🗑 删除' if delete_mode == 'delete' else '💾 不删除'}",
        ]
    )


def parse_positive_int(raw: str, field_name: str) -> int:
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        raise ValidationError(f"{field_name}必须是正整数。")
    if value <= 0:
        raise ValidationError(f"{field_name}必须大于 0。")
    return value


def parse_k3_command(text: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"快3\s+(大|小|单|双|豹子)\s+(\d+)", text.strip())
    if not match:
        return None
    return match.group(1), parse_positive_int(match.group(2), "下注积分")


def parse_blackjack_bet(text: str) -> int | None:
    match = re.fullmatch(r"黑杰克\s+(\d+)", text.strip())
    if not match:
        return None
    return parse_positive_int(match.group(1), "下注积分")


def _get_rake_ratio_value(setting: GameSetting) -> Decimal:
    try:
        return Decimal(setting.rake_ratio or "0")
    except InvalidOperation:
        return Decimal("0")


def _build_blackjack_deck() -> list[int]:
    deck = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10] * 4
    random.shuffle(deck)
    return deck


def blackjack_total(cards: list[int]) -> int:
    total = sum(11 if card == 1 else card for card in cards)
    aces = sum(1 for card in cards if card == 1)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _k3_result_label(dice: list[int]) -> str:
    total = sum(dice)
    size = "大" if total >= 11 else "小"
    parity = "双" if total % 2 == 0 else "单"
    if len(set(dice)) == 1:
        return "豹子"
    return f"{size}{parity}"


def format_k3_help(enabled: bool, rake_ratio: str | None) -> str:
    if not enabled:
        return "🎮 快3当前未开启。"
    return (
        "🎮 快3已开启\n"
        f"💧 抽水比例：{rake_ratio or '0'}\n"
        "玩法：发送 `快3 大 100`、`快3 小 100`、`快3 单 100`、`快3 双 100` 或 `快3 豹子 100` 参与。"
    )


def format_blackjack_help(enabled: bool, rake_ratio: str | None) -> str:
    if not enabled:
        return "🎮 黑杰克当前未开启。"
    return (
        "🎮 黑杰克已开启\n"
        f"💧 抽水比例：{rake_ratio or '0'}\n"
        "玩法：发送 `黑杰克 100` 开局，之后发送 `要牌` 或 `停牌`。"
    )


async def get_active_k3_round(session: AsyncSession, chat_id: int) -> GameRound | None:
    stmt = (
        select(GameRound)
        .where(
            GameRound.chat_id == chat_id,
            GameRound.game_type == "k3",
            GameRound.status == "pending",
        )
        .order_by(GameRound.created_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_active_blackjack_round(session: AsyncSession, chat_id: int, user_id: int) -> tuple[GameRound | None, GameParticipant | None]:
    stmt = (
        select(GameRound, GameParticipant)
        .join(GameParticipant, GameParticipant.round_id == GameRound.id)
        .where(
            GameRound.chat_id == chat_id,
            GameRound.game_type == "blackjack",
            GameRound.status == "player_turn",
            GameParticipant.user_id == user_id,
            GameParticipant.status == "active",
        )
        .order_by(GameRound.created_at.desc())
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        return None, None
    return row[0], row[1]


async def create_or_join_k3_round(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    guess: str,
    bet_points: int,
) -> tuple[GameRound, GameParticipant]:
    round_obj = await get_active_k3_round(session, chat_id)
    if round_obj is None:
        round_obj = GameRound(
            chat_id=chat_id,
            game_type="k3",
            creator_user_id=user_id,
            status="pending",
            settle_at=_now() + dt.timedelta(seconds=60),
            result_data={},
        )
        session.add(round_obj)
        await session.flush()

    existing_stmt = select(GameParticipant).where(
        GameParticipant.round_id == round_obj.id,
        GameParticipant.user_id == user_id,
    )
    existing_result = await session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        raise ValidationError("本局快3你已经下注了，请等待开奖。")

    participant = GameParticipant(
        round_id=round_obj.id,
        chat_id=chat_id,
        user_id=user_id,
        bet_points=bet_points,
        choice_data={"guess": guess},
    )
    session.add(participant)
    await session.flush()
    return round_obj, participant


async def settle_due_k3_rounds(session: AsyncSession) -> list[dict]:
    stmt = select(GameRound).where(
        GameRound.game_type == "k3",
        GameRound.status == "pending",
        GameRound.settle_at.is_not(None),
        GameRound.settle_at <= _now(),
    )
    result = await session.execute(stmt)
    rounds = list(result.scalars().all())
    summaries: list[dict] = []
    for round_obj in rounds:
        participants_result = await session.execute(
            select(GameParticipant).where(GameParticipant.round_id == round_obj.id)
        )
        participants = list(participants_result.scalars().all())
        dice = [random.randint(1, 6) for _ in range(3)]
        label = _k3_result_label(dice)
        total = sum(dice)
        winners: list[dict] = []
        round_obj.result_data = {"dice": dice, "label": label, "total": total}
        round_obj.status = "finished"
        setting = await get_or_create_setting(session, round_obj.chat_id)
        rake_ratio = _get_rake_ratio_value(setting)
        for participant in participants:
            guess = str((participant.choice_data or {}).get("guess") or "")
            multiplier = Decimal("0")
            if guess == "豹子" and label == "豹子":
                multiplier = Decimal("10")
            elif guess != "豹子" and label != "豹子":
                if guess in {label, label[0], label[1]}:
                    multiplier = Decimal("2")
            payout = int((Decimal(participant.bet_points) * multiplier * (Decimal("1") - rake_ratio)).quantize(Decimal("1"))) if multiplier > 0 else 0
            participant.payout_points = payout
            participant.status = "won" if payout > 0 else "lost"
            if payout > 0:
                await change_points(
                    session,
                    round_obj.chat_id,
                    participant.user_id,
                    payout,
                    PointsTxnType.reward.value,
                    reason=f"快3开奖：{label}",
                )
                winners.append({"user_id": participant.user_id, "guess": guess, "payout": payout})
            rake_amount = int((Decimal(participant.bet_points) * multiplier * rake_ratio).quantize(Decimal("1"))) if multiplier > 0 else 0
            if payout > 0 and rake_amount > 0 and setting.rake_owner_user_id:
                await change_points(
                    session,
                    round_obj.chat_id,
                    setting.rake_owner_user_id,
                    rake_amount,
                    PointsTxnType.reward.value,
                    reason="快3抽水",
                )
        summaries.append({"round": round_obj, "winners": winners})
    await session.flush()
    return summaries


async def start_blackjack_round(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    bet_points: int,
) -> tuple[GameRound, GameParticipant]:
    existing_round, existing_participant = await get_active_blackjack_round(session, chat_id, user_id)
    if existing_round is not None and existing_participant is not None:
        raise ValidationError("你已经有一局进行中的黑杰克了，请先发送“要牌”或“停牌”。")

    deck = _build_blackjack_deck()
    player_cards = [deck.pop(), deck.pop()]
    dealer_cards = [deck.pop(), deck.pop()]
    round_obj = GameRound(
        chat_id=chat_id,
        game_type="blackjack",
        creator_user_id=user_id,
        status="player_turn",
        result_data={"deck": deck, "player_cards": player_cards, "dealer_cards": dealer_cards},
    )
    session.add(round_obj)
    await session.flush()
    participant = GameParticipant(
        round_id=round_obj.id,
        chat_id=chat_id,
        user_id=user_id,
        bet_points=bet_points,
        choice_data={"player_cards": player_cards, "dealer_cards": dealer_cards},
    )
    session.add(participant)
    await session.flush()
    return round_obj, participant


def format_blackjack_round_text(participant: GameParticipant, reveal_dealer: bool = False, outcome: str | None = None) -> str:
    choice = participant.choice_data or {}
    player_cards = choice.get("player_cards") or []
    dealer_cards = choice.get("dealer_cards") or []
    player_total = blackjack_total(player_cards)
    shown_dealer = dealer_cards if reveal_dealer else dealer_cards[:1] + ["?"]
    dealer_total = blackjack_total(dealer_cards) if reveal_dealer else "?"
    lines = [
        "🃏 黑杰克",
        f"🎯 下注：{participant.bet_points}",
        f"🙋 你的牌：{player_cards}（{player_total}）",
        f"🤖 庄家牌：{shown_dealer}（{dealer_total}）",
    ]
    if outcome:
        lines.append(outcome)
    return "\n".join(lines)


async def blackjack_hit(
    session: AsyncSession,
    round_obj: GameRound,
    participant: GameParticipant,
) -> tuple[GameRound, GameParticipant, str | None]:
    data = round_obj.result_data or {}
    deck = list(data.get("deck") or [])
    if not deck:
        deck = _build_blackjack_deck()
    player_cards = list(data.get("player_cards") or [])
    player_cards.append(deck.pop())
    data["deck"] = deck
    data["player_cards"] = player_cards
    participant.choice_data = {**(participant.choice_data or {}), "player_cards": player_cards, "dealer_cards": data.get("dealer_cards") or []}
    round_obj.result_data = data
    player_total = blackjack_total(player_cards)
    outcome = None
    if player_total > 21:
        outcome = await finalize_blackjack_round(session, round_obj, participant, "bust")
    await session.flush()
    return round_obj, participant, outcome


async def blackjack_stand(
    session: AsyncSession,
    round_obj: GameRound,
    participant: GameParticipant,
) -> str:
    return await finalize_blackjack_round(session, round_obj, participant, "stand")


async def finalize_blackjack_round(
    session: AsyncSession,
    round_obj: GameRound,
    participant: GameParticipant,
    mode: str,
) -> str:
    data = round_obj.result_data or {}
    player_cards = list(data.get("player_cards") or [])
    dealer_cards = list(data.get("dealer_cards") or [])
    deck = list(data.get("deck") or [])

    player_total = blackjack_total(player_cards)
    if mode != "bust":
        while blackjack_total(dealer_cards) < 17:
            if not deck:
                deck = _build_blackjack_deck()
            dealer_cards.append(deck.pop())
    dealer_total = blackjack_total(dealer_cards)
    round_obj.status = "finished"
    round_obj.result_data = {**data, "deck": deck, "player_cards": player_cards, "dealer_cards": dealer_cards}
    participant.choice_data = {**(participant.choice_data or {}), "player_cards": player_cards, "dealer_cards": dealer_cards}

    setting = await get_or_create_setting(session, round_obj.chat_id)
    rake_ratio = _get_rake_ratio_value(setting)
    payout = 0
    outcome_label = "❌ 本局失败"
    if mode == "bust":
        participant.status = "lost"
    elif dealer_total > 21 or player_total > dealer_total:
        participant.status = "won"
        multiplier = Decimal("2.5") if len(player_cards) == 2 and player_total == 21 else Decimal("2")
        payout = int((Decimal(participant.bet_points) * multiplier * (Decimal("1") - rake_ratio)).quantize(Decimal("1")))
        participant.payout_points = payout
        await change_points(
            session,
            round_obj.chat_id,
            participant.user_id,
            payout,
            PointsTxnType.reward.value,
            reason="黑杰克获胜",
        )
        rake_amount = int((Decimal(participant.bet_points) * multiplier * rake_ratio).quantize(Decimal("1")))
        if rake_amount > 0 and setting.rake_owner_user_id:
            await change_points(
                session,
                round_obj.chat_id,
                setting.rake_owner_user_id,
                rake_amount,
                PointsTxnType.reward.value,
                reason="黑杰克抽水",
            )
        outcome_label = f"✅ 本局获胜，获得 {payout} 积分"
    elif player_total == dealer_total:
        participant.status = "push"
        payout = participant.bet_points
        participant.payout_points = payout
        await change_points(
            session,
            round_obj.chat_id,
            participant.user_id,
            payout,
            PointsTxnType.reward.value,
            reason="黑杰克平局返还",
        )
        outcome_label = f"🤝 本局平局，返还 {payout} 积分"
    else:
        participant.status = "lost"

    await session.flush()
    return outcome_label


async def get_due_finished_game_count(session: AsyncSession, chat_id: int) -> int:
    result = await session.execute(
        select(func.count(GameRound.id)).where(GameRound.chat_id == chat_id, GameRound.status == "finished")
    )
    return int(result.scalar() or 0)


async def list_recent_rounds(session: AsyncSession, chat_id: int, limit: int = 10) -> list[GameRound]:
    result = await session.execute(
        select(GameRound)
        .where(GameRound.chat_id == chat_id)
        .order_by(GameRound.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_round_participants(session: AsyncSession, round_id: int) -> list[GameParticipant]:
    result = await session.execute(
        select(GameParticipant)
        .where(GameParticipant.round_id == round_id)
        .order_by(GameParticipant.created_at.asc())
    )
    return list(result.scalars().all())
