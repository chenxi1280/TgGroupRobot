"""积分排行榜。"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.points.services.points_service_accounts import get_balance
from backend.platform.db.schema.models.core import PointsAccount, TgUser
from backend.platform.db.schema.models.core import PointsTransaction


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


async def get_daily_points_leaderboard(
    session: AsyncSession,
    chat_id: int,
    limit: int = 10,
    *,
    now: dt.datetime | None = None,
) -> list[tuple[int, int, str | None]]:
    local_tz = ZoneInfo("Asia/Shanghai")
    current = now or dt.datetime.now(dt.UTC)
    local_today = current.astimezone(local_tz).date()
    start = dt.datetime.combine(local_today, dt.time.min, tzinfo=local_tz).astimezone(dt.UTC)
    end = start + dt.timedelta(days=1)
    result = await session.execute(
        select(
            PointsTransaction.user_id,
            func.coalesce(func.sum(PointsTransaction.amount), 0).label("earned_points"),
            TgUser.username,
        )
        .join(TgUser, PointsTransaction.user_id == TgUser.id, isouter=True)
        .where(
            PointsTransaction.chat_id == chat_id,
            PointsTransaction.amount > 0,
            PointsTransaction.created_at >= start,
            PointsTransaction.created_at < end,
        )
        .group_by(PointsTransaction.user_id, TgUser.username)
        .order_by(func.sum(PointsTransaction.amount).desc(), PointsTransaction.user_id.asc())
        .limit(limit)
    )
    return [(int(row.user_id), int(row.earned_points or 0), row.username) for row in result]
