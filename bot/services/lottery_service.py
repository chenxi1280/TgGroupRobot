from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import Lottery, LotteryParticipant, LotteryWinner


@dataclass
class JoinResult:
    """参与抽奖结果"""
    success: bool
    reason: Literal[
        "ok",
        "already_joined",
        "lottery_not_found",
        "lottery_not_open",
        "lottery_closed",
        "lottery_completed",
        "insufficient_points",
        "max_participants_reached",
        "not_member_long_enough",
        "outside_join_time",
    ]


async def create_lottery(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    title: str,
    draw_time: dt.datetime,
    prizes: list[dict],
    description: str | None = None,
    min_points: int = 0,
    max_participants: int = 0,
    participation_cost: int = 0,
    join_start_time: dt.datetime | None = None,
    join_end_time: dt.datetime | None = None,
    requirement_days: int = 0,
) -> Lottery:
    """创建抽奖"""
    lottery = Lottery(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        title=title,
        description=description,
        draw_time=draw_time,
        prizes=prizes,
        status="pending",
        min_points=min_points,
        max_participants=max_participants,
        participation_cost=participation_cost,
        join_start_time=join_start_time,
        join_end_time=join_end_time,
        requirement_days=requirement_days,
    )
    session.add(lottery)
    await session.flush()
    return lottery


async def get_lottery(session: AsyncSession, lottery_id: int) -> Lottery | None:
    """获取抽奖信息"""
    stmt = select(Lottery).where(Lottery.id == lottery_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_chat_lotteries(
    session: AsyncSession,
    chat_id: int,
    status: str | None = None,
) -> list[Lottery]:
    """获取群组的抽奖列表"""
    stmt = select(Lottery).where(Lottery.chat_id == chat_id)
    if status:
        stmt = stmt.where(Lottery.status == status)
    stmt = stmt.order_by(Lottery.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_lottery_stats(
    session: AsyncSession,
    chat_id: int,
) -> dict[str, int]:
    """获取群组抽奖统计"""
    stmt = (
        select(Lottery.status, func.count(Lottery.id))
        .where(Lottery.chat_id == chat_id)
        .group_by(Lottery.status)
    )
    result = await session.execute(stmt)
    stats: dict[str, int] = {"total": 0, "pending": 0, "completed": 0, "cancelled": 0}
    for status, count in result.all():
        stats[status] = count
        stats["total"] += count
    return stats


async def can_join_lottery(
    session: AsyncSession,
    lottery: Lottery,
    user_id: int,
    user_points: int,
    member_joined_at: dt.datetime | None = None,
) -> JoinResult:
    """检查用户是否可以参与抽奖"""
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

    # 检查积分要求
    if user_points < lottery.min_points:
        return JoinResult(success=False, reason="insufficient_points")

    # 检查参与费用
    if user_points < lottery.participation_cost:
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
    """参与抽奖"""
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


async def get_lottery_participants(
    session: AsyncSession,
    lottery_id: int,
) -> list[LotteryParticipant]:
    """获取抽奖参与者列表"""
    stmt = select(LotteryParticipant).where(LotteryParticipant.lottery_id == lottery_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_lottery_participant_count(
    session: AsyncSession,
    lottery_id: int,
) -> int:
    """获取抽奖参与人数"""
    stmt = select(func.count(LotteryParticipant.id)).where(
        LotteryParticipant.lottery_id == lottery_id
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


async def create_lottery_winner(
    session: AsyncSession,
    lottery_id: int,
    user_id: int,
    prize_name: str,
    prize_index: int,
) -> LotteryWinner:
    """创建中奖记录"""
    winner = LotteryWinner(
        lottery_id=lottery_id,
        user_id=user_id,
        prize_name=prize_name,
        prize_index=prize_index,
    )
    session.add(winner)
    await session.flush()
    return winner


async def get_lottery_winners(
    session: AsyncSession,
    lottery_id: int,
) -> list[LotteryWinner]:
    """获取抽奖中奖记录"""
    stmt = select(LotteryWinner).where(LotteryWinner.lottery_id == lottery_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_user_lottery_history(
    session: AsyncSession,
    user_id: int,
    chat_id: int | None = None,
) -> list[LotteryWinner]:
    """获取用户中奖历史"""
    stmt = select(LotteryWinner).join(Lottery).where(LotteryWinner.user_id == user_id)
    if chat_id is not None:
        stmt = stmt.where(Lottery.chat_id == chat_id)
    stmt = stmt.order_by(LotteryWinner.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())

