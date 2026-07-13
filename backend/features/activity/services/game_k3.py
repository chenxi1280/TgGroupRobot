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
_CLASSIFY_K3_RESULT_THRESHOLD_11 = 11
_CLASSIFY_K3_RESULT_THRESHOLD_2 = 2
_CLASSIFY_K3_RESULT_THRESHOLD_3 = 3


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


def _k3_result_flags(dice: list[int]) -> dict[str, bool]:
    values = sorted(set(dice))
    is_triple = len(values) == 1
    is_pair = len(values) == _CLASSIFY_K3_RESULT_THRESHOLD_2
    is_straight = len(values) == _CLASSIFY_K3_RESULT_THRESHOLD_3 and values[-1] - values[0] == _CLASSIFY_K3_RESULT_THRESHOLD_2
    has_adjacent = any(values[index + 1] - values[index] == 1 for index in range(max(0, len(values) - 1)))
    return {
        "is_triple": is_triple,
        "is_pair": is_pair,
        "is_straight": is_straight,
        "is_half_straight": len(values) == _CLASSIFY_K3_RESULT_THRESHOLD_3 and has_adjacent and not is_straight,
        "is_misc_six": len(values) == _CLASSIFY_K3_RESULT_THRESHOLD_3 and not has_adjacent,
    }


def _k3_winning_keys(total: int, flags: dict[str, bool]) -> list[str]:
    keys: list[str] = []
    if not flags["is_triple"]:
        keys.extend(["big" if total >= _CLASSIFY_K3_RESULT_THRESHOLD_11 else "small", "even" if total % 2 == 0 else "odd"])
    for flag, key in (
        ("is_triple", "triple"), ("is_pair", "pair"), ("is_straight", "straight"),
        ("is_half_straight", "half_straight"), ("is_misc_six", "misc_six"),
    ):
        if flags[flag]:
            keys.append(key)
    return keys


def classify_k3_result(dice: list[int]) -> dict:
    total = sum(dice)
    flags = _k3_result_flags(dice)
    winning_keys = _k3_winning_keys(total, flags)
    return {
        "total": total,
        "winning_keys": winning_keys,
        "labels": [K3_OPTION_LABELS[key] for key in winning_keys],
        **flags,
    }


def k3_result_label(dice: list[int]) -> str:
    labels = classify_k3_result(dice)["labels"]
    return "、".join(labels) if labels else "未命中"


def is_k3_round_joinable(round_obj: GameRound, current_time=None) -> bool:
    settle_at = round_obj.settle_at
    if settle_at is None:
        return False
    return settle_at > (current_time or now_utc())


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
            GameRound.settle_at.is_not(None),
            GameRound.settle_at > now_utc(),
        )
        .order_by(GameRound.created_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_or_join_k3_round(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    *, guess: str,
    bet_points: int,

    points_chat_id: int | None = None,
) -> tuple[GameRound, GameParticipant]:
    normalized_guess = normalize_k3_guess(guess)
    round_obj = await get_active_k3_round(session, chat_id)
    round_points_chat_id = int(points_chat_id or chat_id)
    if round_obj is not None and not is_k3_round_joinable(round_obj):
        round_obj = None
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
    round_ids = await list_due_k3_round_ids(session)
    summaries: list[dict] = []
    for round_id in round_ids:
        summary = await settle_k3_round(session, round_id)
        if summary is not None:
            summaries.append(summary)
    await session.flush()
    return summaries


async def list_due_k3_round_ids(session: AsyncSession) -> list[int]:
    stmt = select(GameRound.id).where(
        GameRound.game_type == "k3",
        GameRound.status == "pending",
        GameRound.settle_at.is_not(None),
        GameRound.settle_at <= now_utc(),
    )
    result = await session.execute(stmt)
    return [int(round_id) for round_id in result.scalars().all()]


async def _load_k3_round_for_settlement(session, round_id: int):
    round_result = await session.execute(
        select(GameRound).where(
            GameRound.id == round_id,
            GameRound.game_type == "k3",
            GameRound.status == "pending",
            GameRound.settle_at.is_not(None),
            GameRound.settle_at <= now_utc(),
        ).with_for_update()
    )
    round_obj = round_result.scalar_one_or_none()
    if round_obj is None:
        return None
    result = await session.execute(
        select(GameParticipant).where(GameParticipant.round_id == round_obj.id).with_for_update()
    )
    return round_obj, list(result.scalars().all())


def _store_k3_round_result(round_obj, dice: list[int], result: dict, *, points_chat_id: int) -> str:
    label = "、".join(result["labels"]) if result["labels"] else "未命中"
    round_obj.result_data = {
        **(round_obj.result_data or {}),
        "dice": dice,
        "label": label,
        "labels": result["labels"],
        "winning_keys": result["winning_keys"],
        "total": int(result["total"]),
        "points_chat_id": points_chat_id,
    }
    round_obj.status = "finished"
    return label


async def _settle_k3_participant(
    session,
    participant,
    setting,
    *,
    winning_keys: set[str],
    points_chat_id: int,
    label: str,
    rake_ratio: Decimal,
) -> dict | None:
    guess = normalize_k3_guess(str((participant.choice_data or {}).get("guess") or ""))
    multiplier = K3_OPTION_MULTIPLIERS.get(guess, Decimal("0")) if guess in winning_keys else Decimal("0")
    gross = int((Decimal(participant.bet_points) * multiplier).quantize(Decimal("1"))) if multiplier > 0 else 0
    rake = int((Decimal(gross) * rake_ratio).quantize(Decimal("1"))) if gross > 0 else 0
    payout = max(0, gross - rake)
    participant.payout_points = payout
    participant.status = "won" if payout > 0 else "lost"
    if payout <= 0:
        return None
    await change_points(
        session, points_chat_id, participant.user_id, amount=payout,
        txn_type=PointsTxnType.reward.value, reason=f"快三开奖：{label}",
    )
    if rake > 0 and setting.rake_owner_user_id:
        await change_points(
            session, points_chat_id, setting.rake_owner_user_id, amount=rake,
            txn_type=PointsTxnType.reward.value, reason="快三抽水",
        )
    return {
        "user_id": participant.user_id,
        "guess": k3_guess_label(guess),
        "bet": participant.bet_points,
        "payout": payout,
        "net": payout - participant.bet_points,
    }


async def settle_k3_round(session: AsyncSession, round_id: int) -> dict | None:
    loaded = await _load_k3_round_for_settlement(session, round_id)
    if loaded is None:
        return None
    round_obj, participants = loaded
    dice = [random.randint(1, 6) for _ in range(3)]
    result = classify_k3_result(dice)
    winning_keys = set(result["winning_keys"])
    winners: list[dict] = []
    points_chat_id = get_round_points_chat_id(round_obj, round_obj.chat_id)
    label = _store_k3_round_result(round_obj, dice, result, points_chat_id=points_chat_id)
    setting = await get_or_create_setting(session, round_obj.chat_id)
    rake_ratio = get_rake_ratio_value(setting)
    for participant in participants:
        winner = await _settle_k3_participant(
            session, participant, setting, winning_keys=winning_keys,
            points_chat_id=points_chat_id, label=label, rake_ratio=rake_ratio,
        )
        if winner is not None:
            winners.append(winner)
    await session.flush()
    return {"round": round_obj, "winners": winners}
