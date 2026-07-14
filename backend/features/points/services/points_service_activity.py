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


async def _has_signed(session, chat_id: int, user_id: int, *, sign_date: dt.date) -> bool:
    result = await session.execute(select(SignInLog).where(and_(
        SignInLog.chat_id == chat_id,
        SignInLog.user_id == user_id,
        SignInLog.sign_date == sign_date,
    )))
    return result.scalar_one_or_none() is not None


async def _update_sign_streak(session, chat_id: int, user_id: int, *, today: dt.date) -> UserDailyStats:
    stats = await _get_or_create_daily_stats(session, chat_id, user_id, stat_date=today)
    signed_yesterday = await _has_signed(
        session, chat_id, user_id, sign_date=today - dt.timedelta(days=1),
    )
    stats.consecutive_sign_days = stats.consecutive_sign_days + 1 if signed_yesterday else 1
    return stats


def _consecutive_bonus(streak: int, *, required_days: int, bonus_points: int) -> int:
    if required_days <= 0 or bonus_points <= 0 or streak < required_days:
        return 0
    return bonus_points if streak % required_days == 0 else 0


async def _already_signed_result(session, chat_id: int, user_id: int, *, today: dt.date) -> SignResult:
    balance = await get_balance(session, chat_id, user_id)
    stats = await _get_or_create_daily_stats(session, chat_id, user_id, stat_date=today)
    return SignResult(
        success=False, balance=balance, consecutive_days=stats.consecutive_sign_days,
        bonus_points=0, reason="already_signed",
    )


async def _add_sign_log(session, *, chat_id: int, user_id: int, today: dt.date, awarded: int) -> None:
    session.add(SignInLog(
        chat_id=chat_id, user_id=user_id, sign_date=today, points_awarded=awarded,
    ))
    await session.flush()


async def _award_sign_points(session, chat_id: int, user_id: int, *, points: int, bonus: int, streak: int):
    success, balance = await change_points(
        session, chat_id=chat_id, user_id=user_id, amount=points,
        txn_type=PointsTxnType.sign_in.value, reason="签到奖励",
    )
    if bonus > 0:
        await change_points(
            session, chat_id=chat_id, user_id=user_id, amount=bonus,
            txn_type=PointsTxnType.sign_in_consecutive.value,
            reason=f"连续签到{streak}天奖励",
        )
    return success, balance


async def sign_in(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    *, points: int,
    consecutive_days: int = 0,
    consecutive_bonus: int = 0,
) -> SignResult:
    today = dt.datetime.now(dt.UTC).date()
    if await _has_signed(session, chat_id, user_id, sign_date=today):
        return await _already_signed_result(session, chat_id, user_id, today=today)

    stats = await _update_sign_streak(session, chat_id, user_id, today=today)
    streak = stats.consecutive_sign_days
    bonus = _consecutive_bonus(streak, required_days=consecutive_days, bonus_points=consecutive_bonus)

    try:
        await _add_sign_log(
            session, chat_id=chat_id, user_id=user_id, today=today, awarded=points + bonus,
        )
    except IntegrityError:
        await session.rollback()
        bal = await get_balance(session, chat_id, user_id)
        return SignResult(
            success=False,
            balance=bal,
            consecutive_days=streak,
            bonus_points=0,
            reason="already_signed",
        )

    success, balance = await _award_sign_points(
        session, chat_id, user_id, points=points, bonus=bonus, streak=streak,
    )

    return SignResult(
        success=success,
        balance=balance,
        consecutive_days=streak,
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
