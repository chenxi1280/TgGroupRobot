"""签到与活动积分。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.points.services.points_service_accounts import change_points, get_balance
from backend.features.points.services.points_service_types import PointsResult, SignResult
from backend.platform.db.schema.models.core import SignInLog, UserDailyStats
from backend.platform.db.schema.models.enums import PointsTxnType


async def _get_or_create_daily_stats(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    *, stat_date: dt.date,
) -> UserDailyStats:
    res = await session.execute(
        select(UserDailyStats).where(
            and_(
                UserDailyStats.chat_id == chat_id,
                UserDailyStats.user_id == user_id,
                UserDailyStats.stat_date == stat_date,
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
    *, points: int,
    consecutive_days: int = 0,
    consecutive_bonus: int = 0,
) -> SignResult:
    today = dt.datetime.now(dt.UTC).date()
    yesterday = today - dt.timedelta(days=1)

    res = await session.execute(
        select(SignInLog).where(
            and_(
                SignInLog.chat_id == chat_id,
                SignInLog.user_id == user_id,
                SignInLog.sign_date == today,
            )
        )
    )
    if res.scalar_one_or_none() is not None:
        bal = await get_balance(session, chat_id, user_id)
        stats = await _get_or_create_daily_stats(session, chat_id, user_id, stat_date=today)
        return SignResult(
            success=False,
            balance=bal,
            consecutive_days=stats.consecutive_sign_days,
            bonus_points=0,
            reason="already_signed",
        )

    stats = await _get_or_create_daily_stats(session, chat_id, user_id, stat_date=today)
    yesterday_sign = await session.execute(
        select(SignInLog).where(
            and_(
                SignInLog.chat_id == chat_id,
                SignInLog.user_id == user_id,
                SignInLog.sign_date == yesterday,
            )
        )
    )
    if yesterday_sign.scalar_one_or_none() is not None:
        stats.consecutive_sign_days += 1
    else:
        stats.consecutive_sign_days = 1

    total_points = points
    bonus = 0
    if (
        consecutive_days > 0
        and consecutive_bonus > 0
        and stats.consecutive_sign_days >= consecutive_days
        and stats.consecutive_sign_days % consecutive_days == 0
    ):
        bonus = consecutive_bonus
        total_points += bonus

    sign_log = SignInLog(
        chat_id=chat_id,
        user_id=user_id,
        sign_date=today,
        points_awarded=total_points,
    )
    session.add(sign_log)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        bal = await get_balance(session, chat_id, user_id)
        return SignResult(
            success=False,
            balance=bal,
            consecutive_days=stats.consecutive_sign_days,
            bonus_points=0,
            reason="already_signed",
        )

    success, balance = await change_points(
        session,
        chat_id=chat_id,
        user_id=user_id,
        amount=points,
        txn_type=PointsTxnType.sign_in.value,
        reason="签到奖励",
    )

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
        bonus_points=bonus,
    )


async def add_message_points(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    *, points: int,
    daily_limit: int | None = None,
    min_length: int | None = None,
    message_length: int = 0,
) -> PointsResult:
    if min_length is not None and message_length < min_length:
        bal = await get_balance(session, chat_id, user_id)
        return PointsResult(success=False, balance=bal, reason="message_too_short")

    today = dt.datetime.now(dt.UTC).date()
    stats = await _get_or_create_daily_stats(session, chat_id, user_id, stat_date=today)

    if daily_limit is not None and stats.message_points_earned >= daily_limit:
        bal = await get_balance(session, chat_id, user_id)
        return PointsResult(success=False, balance=bal, reason="daily_limit_reached")

    actual_points = points
    if daily_limit is not None:
        remaining = daily_limit - stats.message_points_earned
        actual_points = min(points, remaining)

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

    return PointsResult(
        success=success,
        balance=balance,
        reason=None if success else "insufficient_balance",
    )


async def add_invite_points(
    session: AsyncSession,
    chat_id: int,
    inviter_user_id: int,
    *, points: int,
    daily_limit: int | None = None,
) -> PointsResult:
    today = dt.datetime.now(dt.UTC).date()
    stats = await _get_or_create_daily_stats(session, chat_id, inviter_user_id, stat_date=today)

    if daily_limit is not None and stats.invite_points_earned >= daily_limit:
        bal = await get_balance(session, chat_id, inviter_user_id)
        return PointsResult(success=False, balance=bal, reason="daily_limit_reached")

    actual_points = points
    if daily_limit is not None:
        remaining = daily_limit - stats.invite_points_earned
        actual_points = min(points, remaining)

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

    return PointsResult(
        success=success,
        balance=balance,
        reason=None if success else "insufficient_balance",
    )
