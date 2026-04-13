from __future__ import annotations

import random
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.game_base import get_or_create_setting, get_rake_ratio_value, now_utc
from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.shared.services.base import ValidationError


def k3_result_label(dice: list[int]) -> str:
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
) -> tuple[GameRound, GameParticipant]:
    round_obj = await get_active_k3_round(session, chat_id)
    if round_obj is None:
        import datetime as dt

        round_obj = GameRound(
            chat_id=chat_id,
            game_type="k3",
            creator_user_id=user_id,
            status="pending",
            settle_at=now_utc() + dt.timedelta(seconds=60),
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
        label = k3_result_label(dice)
        total = sum(dice)
        winners: list[dict] = []
        round_obj.result_data = {"dice": dice, "label": label, "total": total}
        round_obj.status = "finished"
        setting = await get_or_create_setting(session, round_obj.chat_id)
        rake_ratio = get_rake_ratio_value(setting)
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
