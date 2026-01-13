"""抽奖验证服务 - 处理抽奖参与条件和验证"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import Lottery, LotteryParticipant
from bot.services.lottery.manager_service import JoinResult, get_lottery


async def can_join_lottery(
    session: AsyncSession,
    lottery: Lottery,
    user_id: int,
    user_points: int,
    member_joined_at: dt.datetime | None = None,
) -> JoinResult:
    """
    检查用户是否可以参与抽奖

    Args:
        session: 数据库会话
        lottery: 抽奖对象
        user_id: 用户ID
        user_points: 用户当前积分
        member_joined_at: 用户加入群组时间

    Returns:
        JoinResult: 验证结果
    """
    # 检查抽奖状态
    if lottery.status != "pending":
        return JoinResult(success=False, reason="lottery_completed")

    now = dt.datetime.now(dt.timezone.utc)
    if lottery.join_start_time and now < lottery.join_start_time:
        return JoinResult(success=False, reason="lottery_not_open")

    if lottery.join_end_time and now > lottery.join_end_time:
        return JoinResult(success=False, reason="lottery_closed")

    # 检查是否已参与
    stmt = select(LotteryParticipant).where(
        LotteryParticipant.lottery_id == lottery.id,
        LotteryParticipant.user_id == user_id,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        return JoinResult(success=False, reason="already_joined")

    # 检查积分要求（最低积分 + 参与费用）
    total_required = (lottery.min_points or 0) + (lottery.participation_cost or 0)
    if user_points < total_required:
        return JoinResult(success=False, reason="insufficient_points")

    # 检查最大参与人数
    if lottery.max_participants > 0:
        count_stmt = select(func.count(LotteryParticipant.id)).where(
            LotteryParticipant.lottery_id == lottery.id
        )
        count_result = await session.execute(count_stmt)
        participant_count = count_result.scalar() or 0
        if participant_count >= lottery.max_participants:
            return JoinResult(success=False, reason="max_participants_reached")

    # 检查入群天数要求
    if lottery.requirement_days > 0 and member_joined_at:
        days_in_group = (now - member_joined_at).days
        if days_in_group < lottery.requirement_days:
            return JoinResult(success=False, reason="not_member_long_enough")

    return JoinResult(success=True, reason="ok")


async def join_lottery(
    session: AsyncSession,
    lottery_id: int,
    user_id: int,
    points_balance: int,
    member_joined_at: dt.datetime | None = None,
) -> JoinResult:
    """
    参与抽奖

    Args:
        session: 数据库会话
        lottery_id: 抽奖ID
        user_id: 用户ID
        points_balance: 用户积分余额
        member_joined_at: 用户加入群组时间

    Returns:
        JoinResult: 参与结果
    """
    from bot.models.core import LotteryParticipant

    # 获取抽奖信息
    lottery = await get_lottery(session, lottery_id)
    if not lottery:
        return JoinResult(success=False, reason="lottery_not_found")

    # 检查是否可以参与
    result = await can_join_lottery(session, lottery, user_id, points_balance, member_joined_at)
    if not result.success:
        return result

    # 创建参与记录
    participant = LotteryParticipant(
        lottery_id=lottery_id,
        user_id=user_id,
        points_balance=points_balance,
    )
    session.add(participant)
    return JoinResult(success=True, reason="ok")
