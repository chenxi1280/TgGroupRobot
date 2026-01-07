"""积分排行榜服务 - 处理积分排名和排行榜功能"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount, TgUser


async def get_leaderboard(
    session: AsyncSession,
    chat_id: int,
    limit: int = 10,
) -> list[tuple[int, int, str | None]]:
    """
    获取积分排行榜

    Args:
        session: 数据库会话
        chat_id: 群组ID
        limit: 返回数量

    Returns:
        [(user_id, balance, username), ...] 按积分降序排列
    """
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
    """
    获取用户在群组中的排名

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        排名（从1开始），如果用户没有积分记录则返回 None
    """
    # 获取用户积分
    user_balance = await get_balance_from_service(session, chat_id, user_id)
    if user_balance == 0:
        return None

    # 统计比该用户积分高的人数
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


async def get_balance_from_service(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> int:
    """从账户服务获取余额（避免循环导入）"""
    from bot.services.points.account_service import get_balance
    return await get_balance(session, chat_id, user_id)
