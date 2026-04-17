from __future__ import annotations

import random
import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.game_base import get_or_create_setting, get_rake_ratio_value, get_round_points_chat_id, now_utc
from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.shared.services.base import ValidationError

BLACKJACK_TURN_SECONDS = 120


def build_blackjack_deck() -> list[int]:
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


def format_blackjack_help(enabled: bool, rake_ratio: str | None) -> str:
    if not enabled:
        return "🎮 黑杰克当前未开启。"
    return (
        "🎮 黑杰克已开启\n"
        "玩法：发送 `黑杰克 100` 开局，之后发送 `要牌` 或 `停牌`。\n"
        "单局 1-2 分钟内操作，超时会自动停牌结算。"
    )


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


async def start_blackjack_round(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    bet_points: int,
    *,
    points_chat_id: int | None = None,
) -> tuple[GameRound, GameParticipant]:
    existing_round, existing_participant = await get_active_blackjack_round(session, chat_id, user_id)
    if existing_round is not None and existing_participant is not None:
        raise ValidationError("你已经有一局进行中的黑杰克了，请先发送“要牌”或“停牌”。")

    deck = build_blackjack_deck()
    player_cards = [deck.pop(), deck.pop()]
    dealer_cards = [deck.pop(), deck.pop()]
    round_obj = GameRound(
        chat_id=chat_id,
        game_type="blackjack",
        creator_user_id=user_id,
        status="player_turn",
        settle_at=now_utc() + dt.timedelta(seconds=BLACKJACK_TURN_SECONDS),
        result_data={
            "deck": deck,
            "player_cards": player_cards,
            "dealer_cards": dealer_cards,
            "points_chat_id": int(points_chat_id or chat_id),
        },
    )
    session.add(round_obj)
    await session.flush()
    participant = GameParticipant(
        round_id=round_obj.id,
        chat_id=chat_id,
        user_id=user_id,
        bet_points=bet_points,
        choice_data={
            "player_cards": player_cards,
            "dealer_cards": dealer_cards,
            "points_chat_id": int(points_chat_id or chat_id),
        },
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
    data = dict(round_obj.result_data or {})
    deck = list(data.get("deck") or [])
    if not deck:
        deck = build_blackjack_deck()
    player_cards = list(data.get("player_cards") or [])
    player_cards.append(deck.pop())
    data["deck"] = deck
    data["player_cards"] = player_cards
    participant.choice_data = {**(participant.choice_data or {}), "player_cards": player_cards, "dealer_cards": data.get("dealer_cards") or []}
    round_obj.result_data = data
    round_obj.settle_at = now_utc() + dt.timedelta(seconds=BLACKJACK_TURN_SECONDS)
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
                deck = build_blackjack_deck()
            dealer_cards.append(deck.pop())
    dealer_total = blackjack_total(dealer_cards)
    round_obj.status = "finished"
    round_obj.settle_at = None
    round_obj.result_data = {**data, "deck": deck, "player_cards": player_cards, "dealer_cards": dealer_cards}
    participant.choice_data = {**(participant.choice_data or {}), "player_cards": player_cards, "dealer_cards": dealer_cards}

    setting = await get_or_create_setting(session, round_obj.chat_id)
    rake_ratio = get_rake_ratio_value(setting)
    points_chat_id = get_round_points_chat_id(round_obj, round_obj.chat_id)
    payout = 0
    outcome_label = "❌ 本局失败"
    if mode == "bust":
        participant.status = "lost"
    elif dealer_total > 21 or player_total > dealer_total:
        participant.status = "won"
        multiplier = Decimal("2.5") if len(player_cards) == 2 and player_total == 21 else Decimal("2")
        gross_payout = int((Decimal(participant.bet_points) * multiplier).quantize(Decimal("1")))
        rake_amount = int((Decimal(gross_payout) * rake_ratio).quantize(Decimal("1")))
        payout = max(0, gross_payout - rake_amount)
        participant.payout_points = payout
        await change_points(
            session,
            points_chat_id,
            participant.user_id,
            payout,
            PointsTxnType.reward.value,
            reason="黑杰克获胜",
        )
        if rake_amount > 0 and setting.rake_owner_user_id:
            await change_points(
                session,
                points_chat_id,
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
            points_chat_id,
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


async def settle_due_blackjack_rounds(session: AsyncSession) -> list[dict]:
    stmt = (
        select(GameRound, GameParticipant)
        .join(GameParticipant, GameParticipant.round_id == GameRound.id)
        .where(
            GameRound.game_type == "blackjack",
            GameRound.status == "player_turn",
            GameRound.settle_at.is_not(None),
            GameRound.settle_at <= now_utc(),
            GameParticipant.status == "active",
        )
    )
    result = await session.execute(stmt)
    summaries: list[dict] = []
    for round_obj, participant in result.all():
        outcome = await finalize_blackjack_round(session, round_obj, participant, "stand")
        summaries.append({"round": round_obj, "participant": participant, "outcome": f"⏰ 超时自动停牌\n{outcome}"})
    await session.flush()
    return summaries
