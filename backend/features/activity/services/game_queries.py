from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.expansion import GameParticipant, GameRound


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
