from __future__ import annotations

import random
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.game_base import (
    get_or_create_setting,
    get_rake_ratio_value,
    get_round_points_chat_id,
    now_utc,
)
from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.shared.services.base import ValidationError

K3_ROUND_SECONDS = 60

K3_OPTION_LABELS: dict[str, str] = {
    "small": "小",
    "big": "大",
    "odd": "单",
    "even": "双",
    "triple": "豹子通杀",
    "pair": "对子号",
    "half_straight": "半顺号",
    "straight": "三连号",
    "misc_six": "杂六号",
}

K3_OPTION_MULTIPLIERS: dict[str, Decimal] = {
    "small": Decimal("2"),
    "big": Decimal("2"),
    "odd": Decimal("2"),
    "even": Decimal("2"),
    "triple": Decimal("20"),
    "pair": Decimal("2.2"),
    "half_straight": Decimal("2.4"),
    "straight": Decimal("6"),
    "misc_six": Decimal("5"),
}

K3_OPTION_ALIASES: dict[str, str] = {
    "小": "small",
    "大": "big",
    "单": "odd",
    "双": "even",
    "豹子": "triple",
    "豹子通杀": "triple",
    "对子": "pair",
    "对子号": "pair",
    "半顺": "half_straight",
    "半顺号": "half_straight",
    "三连": "straight",
    "三连号": "straight",
    "杂六": "misc_six",
    "杂六号": "misc_six",
    **{key: key for key in K3_OPTION_LABELS},
}


def normalize_k3_guess(raw: str) -> str:
    guess = K3_OPTION_ALIASES.get(str(raw).strip())
    if not guess:
        raise ValidationError("快三玩法无效，请选择大/小/单/双/豹子/对子/半顺/三连/杂六。")
    return guess


def k3_guess_label(guess: str) -> str:
    return K3_OPTION_LABELS.get(normalize_k3_guess(guess), str(guess))


def classify_k3_result(dice: list[int]) -> dict:
    total = sum(dice)
    unique_values = sorted(set(dice))
    is_triple = len(unique_values) == 1
    is_pair = len(unique_values) == 2
    is_straight = len(unique_values) == 3 and unique_values[-1] - unique_values[0] == 2
    has_adjacent = any(
        unique_values[idx + 1] - unique_values[idx] == 1
        for idx in range(max(0, len(unique_values) - 1))
    )
    is_half_straight = len(unique_values) == 3 and has_adjacent and not is_straight
    is_misc_six = len(unique_values) == 3 and not has_adjacent

    winning_keys: list[str] = []
    if not is_triple:
        winning_keys.append("big" if total >= 11 else "small")
        winning_keys.append("even" if total % 2 == 0 else "odd")
    if is_triple:
        winning_keys.append("triple")
    if is_pair:
        winning_keys.append("pair")
    if is_straight:
        winning_keys.append("straight")
    if is_half_straight:
        winning_keys.append("half_straight")
    if is_misc_six:
        winning_keys.append("misc_six")

    return {
        "total": total,
        "winning_keys": winning_keys,
        "labels": [K3_OPTION_LABELS[key] for key in winning_keys],
        "is_triple": is_triple,
        "is_pair": is_pair,
        "is_straight": is_straight,
        "is_half_straight": is_half_straight,
        "is_misc_six": is_misc_six,
    }


def k3_result_label(dice: list[int]) -> str:
    labels = classify_k3_result(dice)["labels"]
    return "、".join(labels) if labels else "未命中"


def format_k3_help(enabled: bool, rake_ratio: str | None) -> str:
    if not enabled:
        return "🎮 快三当前未开启。"
    return (
        "🎮 快三已开启\n"
        "玩法：发送 `快三 大 100`、`快三 对子 100`、`快三 半顺 100`、`快三 三连 100` 或 `快三 杂六 100` 参与。\n"
        "赔率：大小单双 2倍，豹子通杀 20倍，对子 2.2倍，半顺 2.4倍，三连 6倍，杂六 5倍。"
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


async def create_or_join_k3_round(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    guess: str,
    bet_points: int,
    *,
    points_chat_id: int | None = None,
) -> tuple[GameRound, GameParticipant]:
    normalized_guess = normalize_k3_guess(guess)
    round_obj = await get_active_k3_round(session, chat_id)
    round_points_chat_id = int(points_chat_id or chat_id)
    if round_obj is None:
        import datetime as dt

        round_obj = GameRound(
            chat_id=chat_id,
            game_type="k3",
            creator_user_id=user_id,
            status="pending",
            settle_at=now_utc() + dt.timedelta(seconds=K3_ROUND_SECONDS),
            result_data={"points_chat_id": round_points_chat_id},
        )
        session.add(round_obj)
        await session.flush()
    else:
        round_points_chat_id = get_round_points_chat_id(round_obj, round_points_chat_id)

    existing_stmt = select(GameParticipant).where(
        GameParticipant.round_id == round_obj.id,
        GameParticipant.user_id == user_id,
    )
    existing_result = await session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        raise ValidationError("本局快三你已经下注了，请等待开奖。")

    participant = GameParticipant(
        round_id=round_obj.id,
        chat_id=chat_id,
        user_id=user_id,
        bet_points=bet_points,
        choice_data={"guess": normalized_guess, "points_chat_id": round_points_chat_id},
    )
    session.add(participant)
    await session.flush()
    return round_obj, participant


async def settle_due_k3_rounds(session: AsyncSession) -> list[dict]:
    stmt = select(GameRound).where(
        GameRound.game_type == "k3",
        GameRound.status == "pending",
        GameRound.settle_at.is_not(None),
        GameRound.settle_at <= now_utc(),
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
        result = classify_k3_result(dice)
        label = "、".join(result["labels"]) if result["labels"] else "未命中"
        total = int(result["total"])
        winning_keys = set(result["winning_keys"])
        winners: list[dict] = []
        points_chat_id = get_round_points_chat_id(round_obj, round_obj.chat_id)
        round_obj.result_data = {
            **(round_obj.result_data or {}),
            "dice": dice,
            "label": label,
            "labels": result["labels"],
            "winning_keys": result["winning_keys"],
            "total": total,
            "points_chat_id": points_chat_id,
        }
        round_obj.status = "finished"
        setting = await get_or_create_setting(session, round_obj.chat_id)
        rake_ratio = get_rake_ratio_value(setting)
        for participant in participants:
            guess = normalize_k3_guess(str((participant.choice_data or {}).get("guess") or ""))
            multiplier = K3_OPTION_MULTIPLIERS.get(guess, Decimal("0")) if guess in winning_keys else Decimal("0")
            gross_payout = int((Decimal(participant.bet_points) * multiplier).quantize(Decimal("1"))) if multiplier > 0 else 0
            rake_amount = int((Decimal(gross_payout) * rake_ratio).quantize(Decimal("1"))) if gross_payout > 0 else 0
            payout = max(0, gross_payout - rake_amount)
            participant.payout_points = payout
            participant.status = "won" if payout > 0 else "lost"
            if payout > 0:
                await change_points(
                    session,
                    points_chat_id,
                    participant.user_id,
                    payout,
                    PointsTxnType.reward.value,
                    reason=f"快三开奖：{label}",
                )
                winners.append({"user_id": participant.user_id, "guess": k3_guess_label(guess), "payout": payout})
            if payout > 0 and rake_amount > 0 and setting.rake_owner_user_id:
                await change_points(
                    session,
                    points_chat_id,
                    setting.rake_owner_user_id,
                    rake_amount,
                    PointsTxnType.reward.value,
                    reason="快三抽水",
                )
        summaries.append({"round": round_obj, "winners": winners})
    await session.flush()
    return summaries
