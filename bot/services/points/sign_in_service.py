"""签到积分服务 - 处理用户签到和连续签到奖励"""

from __future__ import annotations

import datetime as dt
from typing import NamedTuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount, PointsTransaction, SignInLog, UserDailyStats
from bot.models.enums import PointsTxnType
from bot.services.points.account_service import _get_or_create_account, change_points, get_balance


class SignResult(NamedTuple):
    """签到结果"""
    success: bool
    balance: int
    consecutive_days: int
    bonus_points: int
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


async def sign_in(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    points: int,
    consecutive_days: int = 0,
    consecutive_bonus: int = 0,
) -> SignResult:
    """
    签到获取积分（支持连续签到奖励）

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID
        points: 基础签到积分
        consecutive_days: 连续签到奖励门槛天数
        consecutive_bonus: 连续签到奖励积分

    Returns:
        SignResult: 签到结果
    """
    today = dt.datetime.now(dt.UTC).date()
    yesterday = today - dt.timedelta(days=1)

    # 检查今日是否已签到
    res = await session.execute(
        select(SignInLog).where(
            and_(
                SignInLog.chat_id == chat_id,
                SignInLog.user_id == user_id,
                SignInLog.sign_date == today
            )
        )
    )
    if res.scalar_one_or_none() is not None:
        bal = await get_balance(session, chat_id, user_id)
        stats = await _get_or_create_daily_stats(session, chat_id, user_id, today)
        return SignResult(
            success=False,
            balance=bal,
            consecutive_days=stats.consecutive_sign_days,
            bonus_points=0,
            reason="already_signed"
        )

    # 获取每日统计（用于连续签到计算）
    stats = await _get_or_create_daily_stats(session, chat_id, user_id, today)

    # 检查昨天是否签到
    yesterday_sign = await session.execute(
        select(SignInLog).where(
            and_(
                SignInLog.chat_id == chat_id,
                SignInLog.user_id == user_id,
                SignInLog.sign_date == yesterday
            )
        )
    )
    if yesterday_sign.scalar_one_or_none() is not None:
        # 连续签到
        stats.consecutive_sign_days += 1
    else:
        # 重置连续天数
        stats.consecutive_sign_days = 1

    # 计算总积分（基础+奖励）
    total_points = points
    bonus = 0
    if consecutive_days > 0 and consecutive_bonus > 0 and stats.consecutive_sign_days >= consecutive_days and stats.consecutive_sign_days % consecutive_days == 0:
        bonus = consecutive_bonus
        total_points += bonus

    # 创建签到日志
    sign_log = SignInLog(
        chat_id=chat_id,
        user_id=user_id,
        sign_date=today,
        points_awarded=total_points,
    )
    session.add(sign_log)
    await session.flush()

    # 添加基础签到积分
    success, balance = await change_points(
        session,
        chat_id=chat_id,
        user_id=user_id,
        amount=points,  # 只添加基础积分，奖励积分在下面单独添加
        txn_type=PointsTxnType.sign_in.value,
        reason="签到奖励",
    )

    # 添加连续签到奖励记录（如果有）
    if bonus > 0:
        await change_points(
            session,
            chat_id=chat_id,
            user_id=user_id,
            amount=bonus,
            txn_type=PointsTxnType.sign_in_consecutive.value,
            reason=f"连续签到{stats.consecutive_sign_days}天奖励",
        )

    return SignResult(
        success=success,
        balance=balance,
        consecutive_days=stats.consecutive_sign_days,
        bonus_points=bonus
    )
