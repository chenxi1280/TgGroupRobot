from __future__ import annotations

import datetime as dt

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.lottery_service_types import JoinResult
from backend.platform.db.schema.models.core import InviteTracking, Lottery, LotteryParticipant
from backend.platform.db.schema.models.expansion import EngagementChatStat


async def can_join_lottery(
    session: AsyncSession,
    lottery: Lottery,
    user_id: int,
    *, user_points: int,
    member_joined_at: dt.datetime | None = None,
) -> JoinResult:
    if lottery.status != "pending":
        return JoinResult(success=False, reason="lottery_completed")

    now = dt.datetime.now(dt.timezone.utc)
    if lottery.join_start_time and now < lottery.join_start_time:
        return JoinResult(success=False, reason="lottery_not_open")
    if lottery.join_end_time and now > lottery.join_end_time:
        return JoinResult(success=False, reason="lottery_closed")

    result = await session.execute(
        select(LotteryParticipant).where(
            LotteryParticipant.lottery_id == lottery.id,
            LotteryParticipant.user_id == user_id,
        )
    )
    if result.scalar_one_or_none() is not None:
        return JoinResult(success=False, reason="already_joined")

    total_required = (lottery.min_points or 0) + (lottery.participation_cost or 0)
    if user_points < total_required:
        return JoinResult(success=False, reason="insufficient_points")

    qualification_rules = lottery.qualification_rules or {}
    if qualification_rules.get("selection_mode") == "ranking_random":
        return JoinResult(success=False, reason="ranking_auto_selection")
    window_days = int(qualification_rules.get("window_days") or 0)

    if lottery.lottery_type == "invite":
        required_invites = int(qualification_rules.get("required_invites") or 0)
        if required_invites > 0:
            invite_stmt = select(func.count(InviteTracking.id)).where(
                InviteTracking.chat_id == lottery.chat_id,
                InviteTracking.inviter_user_id == user_id,
            )
            if window_days > 0:
                invite_stmt = invite_stmt.where(InviteTracking.joined_at >= now - dt.timedelta(days=window_days))
            invite_result = await session.execute(invite_stmt)
            if int(invite_result.scalar() or 0) < required_invites:
                return JoinResult(success=False, reason="insufficient_invites")

    if lottery.lottery_type == "activity":
        required_activity = int(qualification_rules.get("required_activity_count") or 0)
        if required_activity > 0:
            activity_stmt = select(func.coalesce(func.sum(EngagementChatStat.message_count), 0)).where(
                EngagementChatStat.chat_id == lottery.chat_id,
                EngagementChatStat.user_id == user_id,
            )
            if window_days > 0:
                activity_stmt = activity_stmt.where(EngagementChatStat.biz_date >= (now - dt.timedelta(days=window_days)).date())
            activity_result = await session.execute(activity_stmt)
            if int(activity_result.scalar() or 0) < required_activity:
                return JoinResult(success=False, reason="insufficient_activity")

    if lottery.max_participants > 0:
        count_result = await session.execute(select(func.count(LotteryParticipant.id)).where(LotteryParticipant.lottery_id == lottery.id))
        if (count_result.scalar() or 0) >= lottery.max_participants:
            return JoinResult(success=False, reason="max_participants_reached")

    if lottery.requirement_days > 0 and member_joined_at:
        if (now - member_joined_at).days < lottery.requirement_days:
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
