"""活动积分服务 - 处理发言和邀请等活动的积分奖励"""

from __future__ import annotations

import datetime as dt
from typing import NamedTuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount, PointsTransaction, UserDailyStats
from bot.models.enums import PointsTxnType
from bot.services.points.account_service import _get_or_create_account, change_points, get_balance


class PointsResult(NamedTuple):
    """积分变动结果"""
    success: bool
    balance: int
    reason: str | None = None


async def _get_or_create_daily_stats(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    stat_date: dt.date,
) -> UserDailyStats:
    """获取或创建每日统计"""
    res = await session.execute(
        select(UserDailyStats).where(
            and_(
                UserDailyStats.chat_id == chat_id,
                UserDailyStats.user_id == user_id,
                UserDailyStats.stat_date == stat_date
            )
        )
    )
    stats = res.scalar_one_or_none()
    if stats is None:
        stats = UserDailyStats(chat_id=chat_id, user_id=user_id, stat_date=stat_date)
        session.add(stats)
        await session.flush()
    return stats


async def add_message_points(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    points: int,
    daily_limit: int | None = None,
    min_length: int | None = None,
    message_length: int = 0,
) -> PointsResult:
    """
    添加发言积分（支持每日上限和最小字数）

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID
        points: 每次发言获得积分
        daily_limit: 每日上限（None=无限制）
        min_length: 最小字数（None=无限制）
        message_length: 消息长度

    Returns:
        PointsResult: 积分变动结果
    """
    # 检查字数限制
    if min_length is not None and message_length < min_length:
        bal = await get_balance(session, chat_id, user_id)
        return PointsResult(success=False, balance=bal, reason="message_too_short")

    today = dt.datetime.now(dt.UTC).date()
    stats = await _get_or_create_daily_stats(session, chat_id, user_id, today)

    # 检查每日上限
    if daily_limit is not None and stats.message_points_earned >= daily_limit:
        bal = await get_balance(session, chat_id, user_id)
        return PointsResult(success=False, balance=bal, reason="daily_limit_reached")

    # 计算实际可获得的积分
    actual_points = points
    if daily_limit is not None:
        remaining = daily_limit - stats.message_points_earned
        actual_points = min(points, remaining)

    # 添加积分
    success, balance = await change_points(
        session,
        chat_id=chat_id,
        user_id=user_id,
        amount=actual_points,
        txn_type=PointsTxnType.message.value,
        reason="发言奖励",
    )

    if success:
        stats.message_points_earned += actual_points

    return PointsResult(success=success, balance=balance, reason=None if success else "insufficient_balance")


async def add_invite_points(
    session: AsyncSession,
    chat_id: int,
    inviter_user_id: int,
    points: int,
    daily_limit: int | None = None,
) -> PointsResult:
    """
    添加邀请积分（支持每日上限）

    Args:
        session: 数据库会话
        chat_id: 群组ID
        inviter_user_id: 邀请人用户ID
        points: 每次邀请获得积分
        daily_limit: 每日上限（None=无限制）

    Returns:
        PointsResult: 积分变动结果
    """
    today = dt.datetime.now(dt.UTC).date()
    stats = await _get_or_create_daily_stats(session, chat_id, inviter_user_id, today)

    # 检查每日上限
    if daily_limit is not None and stats.invite_points_earned >= daily_limit:
        bal = await get_balance(session, chat_id, inviter_user_id)
        return PointsResult(success=False, balance=bal, reason="daily_limit_reached")

    # 计算实际可获得的积分
    actual_points = points
    if daily_limit is not None:
        remaining = daily_limit - stats.invite_points_earned
        actual_points = min(points, remaining)

    # 添加积分
    success, balance = await change_points(
        session,
        chat_id=chat_id,
        user_id=inviter_user_id,
        amount=actual_points,
        txn_type=PointsTxnType.invite.value,
        reason="邀请奖励",
    )

    if success:
        stats.invite_points_earned += actual_points
        stats.invites_count += 1

    return PointsResult(success=success, balance=balance, reason=None if success else "insufficient_balance")
