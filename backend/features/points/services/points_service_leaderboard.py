"""积分排行榜。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.points.services.points_service_accounts import get_balance
from backend.platform.db.schema.models.core import PointsAccount, TgUser


async def get_leaderboard(
    session: AsyncSession,
    chat_id: int,
    limit: int = 10,
) -> list[tuple[int, int, str | None]]:
    result = await session.execute(
        select(
            PointsAccount.user_id,
            PointsAccount.balance,
            TgUser.username,
        )
        .join(TgUser, PointsAccount.user_id == TgUser.id)
        .where(PointsAccount.chat_id == chat_id)
        .order_by(PointsAccount.balance.desc())
        .limit(limit)
    )
    return [(row.user_id, row.balance, row.username) for row in result]


async def get_user_rank(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> int | None:
    user_balance = await get_balance(session, chat_id, user_id)
    if user_balance is None or user_balance == 0:
        return None

    result = await session.execute(
        select(func.count(PointsAccount.id)).where(
            func.and_(
                PointsAccount.chat_id == chat_id,
                PointsAccount.balance > user_balance,
            )
        )
    )
    count = result.scalar() or 0
    return count + 1
