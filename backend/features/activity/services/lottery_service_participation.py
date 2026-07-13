from __future__ import annotations

import datetime as dt

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.lottery_service_types import JoinResult
from backend.platform.db.schema.models.core import InviteTracking, Lottery, LotteryParticipant
from backend.platform.db.schema.models.expansion import EngagementChatStat


def _join_precondition_failure(
    lottery: Lottery, *, now: dt.datetime
) -> str | None:
    if lottery.status != "pending":
        return "lottery_completed"
    if lottery.join_start_time and now < lottery.join_start_time:
        return "lottery_not_open"
    if lottery.join_end_time and now > lottery.join_end_time:
        return "lottery_closed"
    return None


def _qualification_failure(lottery: Lottery, *, user_points: int) -> str | None:
    required = (lottery.min_points or 0) + (lottery.participation_cost or 0)
    if user_points < required:
        return "insufficient_points"
    rules = lottery.qualification_rules or {}
    return "ranking_auto_selection" if rules.get("selection_mode") == "ranking_random" else None


async def _has_joined_lottery(session, *, lottery_id: int, user_id: int) -> bool:
    result = await session.execute(
        select(LotteryParticipant).where(
            LotteryParticipant.lottery_id == lottery_id,
            LotteryParticipant.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _has_required_invites(
    session, *, lottery: Lottery, user_id: int, rules: dict,
    now: dt.datetime, window_days: int,
) -> bool:
    required = int(rules.get("required_invites") or 0)
    if lottery.lottery_type != "invite" or required <= 0:
        return True
    statement = select(func.count(InviteTracking.id)).where(
        InviteTracking.chat_id == lottery.chat_id,
        InviteTracking.inviter_user_id == user_id,
    )
    if window_days > 0:
        statement = statement.where(
            InviteTracking.joined_at >= now - dt.timedelta(days=window_days)
        )
    result = await session.execute(statement)
    return int(result.scalar() or 0) >= required


async def _has_required_activity(
    session, *, lottery: Lottery, user_id: int, rules: dict,
    now: dt.datetime, window_days: int,
) -> bool:
    required = int(rules.get("required_activity_count") or 0)
    if lottery.lottery_type != "activity" or required <= 0:
        return True
    statement = select(
        func.coalesce(func.sum(EngagementChatStat.message_count), 0)
    ).where(
        EngagementChatStat.chat_id == lottery.chat_id,
        EngagementChatStat.user_id == user_id,
    )
    if window_days > 0:
        statement = statement.where(
            EngagementChatStat.biz_date >= (now - dt.timedelta(days=window_days)).date()
        )
    result = await session.execute(statement)
    return int(result.scalar() or 0) >= required


async def _lottery_has_capacity(session, lottery: Lottery) -> bool:
    if lottery.max_participants <= 0:
        return True
    result = await session.execute(
        select(func.count(LotteryParticipant.id)).where(
            LotteryParticipant.lottery_id == lottery.id
        )
    )
    return int(result.scalar() or 0) < lottery.max_participants


async def _query_qualification_failure(
    session, *, lottery: Lottery, user_id: int, rules: dict,
    now: dt.datetime, window_days: int,
) -> str | None:
    if not await _has_required_invites(
        session, lottery=lottery, user_id=user_id, rules=rules,
        now=now, window_days=window_days,
    ):
        return "insufficient_invites"
    if not await _has_required_activity(
        session, lottery=lottery, user_id=user_id, rules=rules,
        now=now, window_days=window_days,
    ):
        return "insufficient_activity"
    if not await _lottery_has_capacity(session, lottery):
        return "max_participants_reached"
    return None


def _membership_too_short(
    lottery: Lottery, *, now: dt.datetime, joined_at: dt.datetime | None
) -> bool:
    return bool(
        lottery.requirement_days > 0 and joined_at
        and (now - joined_at).days < lottery.requirement_days
    )


async def can_join_lottery(
    session: AsyncSession,
    lottery: Lottery,
    user_id: int,
    *, user_points: int,
    member_joined_at: dt.datetime | None = None,
) -> JoinResult:
    now = dt.datetime.now(dt.timezone.utc)
    failure = _join_precondition_failure(lottery, now=now)
    if failure is not None:
        return JoinResult(success=False, reason=failure)
    if await _has_joined_lottery(session, lottery_id=lottery.id, user_id=user_id):
        return JoinResult(success=False, reason="already_joined")
    failure = _qualification_failure(lottery, user_points=user_points)
    if failure is not None:
        return JoinResult(success=False, reason=failure)
    rules = lottery.qualification_rules or {}
    window_days = int(rules.get("window_days") or 0)
    failure = await _query_qualification_failure(
        session, lottery=lottery, user_id=user_id, rules=rules,
        now=now, window_days=window_days,
    )
    if failure is not None:
        return JoinResult(success=False, reason=failure)
    if _membership_too_short(lottery, now=now, joined_at=member_joined_at):
        return JoinResult(success=False, reason="not_member_long_enough")
    return JoinResult(success=True, reason="ok")


async def join_lottery(
    session: AsyncSession,
    lottery_id: int,
    user_id: int,
    *, points_balance: int,
    member_joined_at: dt.datetime | None = None,
) -> JoinResult:
    result = await session.execute(select(Lottery).where(Lottery.id == lottery_id).with_for_update())
    lottery = result.scalar_one_or_none()
    if not lottery:
        return JoinResult(success=False, reason="lottery_not_found")
    result = await can_join_lottery(session, lottery, user_id, user_points=points_balance, member_joined_at=member_joined_at)
    if not result.success:
        return result
    session.add(LotteryParticipant(lottery_id=lottery_id, user_id=user_id, points_balance=points_balance))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return JoinResult(success=False, reason="already_joined")
    return JoinResult(success=True, reason="ok")
