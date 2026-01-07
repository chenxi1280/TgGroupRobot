"""抽奖管理服务 - 处理抽奖的创建、查询和统计"""

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
    """
    创建抽奖

    Args:
        session: 数据库会话
        chat_id: 群组ID
        created_by_user_id: 创建者用户ID
        title: 抽奖标题
        draw_time: 开奖时间
        prizes: 奖品列表
        description: 抽奖描述
        min_points: 最低积分要求
        max_participants: 最大参与人数（0=无限制）
        participation_cost: 参与费用（积分）
        join_start_time: 报名开始时间
        join_end_time: 报名结束时间
        requirement_days: 入群天数要求

    Returns:
        创建的抽奖对象
    """
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
    """
    获取抽奖信息

    Args:
        session: 数据库会话
        lottery_id: 抽奖ID

    Returns:
        抽奖对象，不存在则返回 None
    """
    stmt = select(Lottery).where(Lottery.id == lottery_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_chat_lotteries(
    session: AsyncSession,
    chat_id: int,
    status: str | None = None,
) -> list[Lottery]:
    """
    获取群组的抽奖列表

    Args:
        session: 数据库会话
        chat_id: 群组ID
        status: 抽奖状态过滤（None=全部）

    Returns:
        抽奖列表，按创建时间倒序
    """
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
    """
    获取群组抽奖统计

    Args:
        session: 数据库会话
        chat_id: 群组ID

    Returns:
        统计数据字典 {status: count}
    """
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


async def get_lottery_participants(
    session: AsyncSession,
    lottery_id: int,
) -> list[LotteryParticipant]:
    """
    获取抽奖参与者列表

    Args:
        session: 数据库会话
        lottery_id: 抽奖ID

    Returns:
        参与者列表
    """
    stmt = select(LotteryParticipant).where(LotteryParticipant.lottery_id == lottery_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_lottery_participant_count(
    session: AsyncSession,
    lottery_id: int,
) -> int:
    """
    获取抽奖参与人数

    Args:
        session: 数据库会话
        lottery_id: 抽奖ID

    Returns:
        参与人数
    """
    stmt = select(func.count(LotteryParticipant.id)).where(
        LotteryParticipant.lottery_id == lottery_id
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


async def get_lottery_winners(
    session: AsyncSession,
    lottery_id: int,
) -> list[LotteryWinner]:
    """
    获取抽奖中奖记录

    Args:
        session: 数据库会话
        lottery_id: 抽奖ID

    Returns:
        中奖记录列表
    """
    stmt = select(LotteryWinner).where(LotteryWinner.lottery_id == lottery_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_user_lottery_history(
    session: AsyncSession,
    user_id: int,
    chat_id: int | None = None,
) -> list[LotteryWinner]:
    """
    获取用户中奖历史

    Args:
        session: 数据库会话
        user_id: 用户ID
        chat_id: 群组ID（None=全部群组）

    Returns:
        中奖记录列表，按时间倒序
    """
    stmt = select(LotteryWinner).join(Lottery).where(LotteryWinner.user_id == user_id)
    if chat_id is not None:
        stmt = stmt.where(Lottery.chat_id == chat_id)
    stmt = stmt.order_by(LotteryWinner.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())
