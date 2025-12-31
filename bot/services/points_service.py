from __future__ import annotations

import datetime as dt
from typing import NamedTuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount, PointsTransaction, SignInLog, TgUser, UserDailyStats
from bot.models.enums import PointsTxnType


class SignResult(NamedTuple):
    """签到结果"""
    success: bool
    balance: int
    consecutive_days: int
    bonus_points: int
    reason: str | None = None


class PointsResult(NamedTuple):
    """积分变动结果"""
    success: bool
    balance: int
    reason: str | None = None


async def get_balance(session: AsyncSession, chat_id: int, user_id: int) -> int:
    """获取用户在群组中的积分余额"""
    res = await session.execute(
        select(PointsAccount.balance).where(and_(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id))
    )
    bal = res.scalar_one_or_none()
    return int(bal or 0)


async def _get_or_create_account(session: AsyncSession, chat_id: int, user_id: int) -> PointsAccount:
    """获取或创建积分账户"""
    res = await session.execute(
        select(PointsAccount).where(and_(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id))
    )
    acc = res.scalar_one_or_none()
    if acc is None:
        acc = PointsAccount(chat_id=chat_id, user_id=user_id, balance=0)
        session.add(acc)
        await session.flush()
    return acc


async def _get_or_create_daily_stats(session: AsyncSession, chat_id: int, user_id: int, stat_date: dt.date) -> UserDailyStats:
    """获取或创建每日统计"""
    res = await session.execute(
        select(UserDailyStats).where(
            and_(UserDailyStats.chat_id == chat_id, UserDailyStats.user_id == user_id, UserDailyStats.stat_date == stat_date)
        )
    )
    stats = res.scalar_one_or_none()
    if stats is None:
        stats = UserDailyStats(chat_id=chat_id, user_id=user_id, stat_date=stat_date)
        session.add(stats)
        await session.flush()
    return stats


async def change_points(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    amount: int,
    txn_type: str,
    reason: str | None = None,
) -> tuple[bool, int]:
    """
    修改用户积分

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID
        amount: 积分变动量（正数为增加，负数为减少）
        txn_type: 交易类型
        reason: 变动原因

    Returns:
        (是否成功, 变动后余额)
        失败原因：余额不足时无法扣款
    """
    acc = await _get_or_create_account(session, chat_id, user_id)

    # 检查余额是否足够（扣款时）
    if amount < 0 and acc.balance < -amount:
        balance = acc.balance
        return False, balance

    acc.balance += amount
    session.add(
        PointsTransaction(
            chat_id=chat_id,
            user_id=user_id,
            txn_type=txn_type,
            amount=amount,
            reason=reason,
        )
    )
    await session.flush()
    return True, acc.balance


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
        select(SignInLog).where(and_(SignInLog.chat_id == chat_id, SignInLog.user_id == user_id, SignInLog.sign_date == today))
    )
    if res.scalar_one_or_none() is not None:
        bal = await get_balance(session, chat_id, user_id)
        stats = await _get_or_create_daily_stats(session, chat_id, user_id, today)
        return SignResult(success=False, balance=bal, consecutive_days=stats.consecutive_sign_days, bonus_points=0, reason="already_signed")

    # 获取每日统计（用于连续签到计算）
    stats = await _get_or_create_daily_stats(session, chat_id, user_id, today)

    # 检查昨天是否签到
    yesterday_sign = await session.execute(
        select(SignInLog).where(and_(SignInLog.chat_id == chat_id, SignInLog.user_id == user_id, SignInLog.sign_date == yesterday))
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

    # 添加积分
    success, balance = await change_points(
        session,
        chat_id=chat_id,
        user_id=user_id,
        amount=total_points,
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

    return SignResult(success=success, balance=balance, consecutive_days=stats.consecutive_sign_days, bonus_points=bonus)


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


async def get_leaderboard(session: AsyncSession, chat_id: int, limit: int = 10) -> list[tuple[int, int, str | None]]:
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


async def get_user_rank(session: AsyncSession, chat_id: int, user_id: int) -> int | None:
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
    user_balance = await get_balance(session, chat_id, user_id)
    if user_balance == 0:
        return None

    # 统计比该用户积分高的人数
    result = await session.execute(
        select(func.count(PointsAccount.id)).where(
            and_(
                PointsAccount.chat_id == chat_id,
                PointsAccount.balance > user_balance,
            )
        )
    )
    count = result.scalar() or 0
    return count + 1
