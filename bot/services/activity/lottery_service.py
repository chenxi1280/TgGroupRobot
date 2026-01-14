"""抽奖服务 - 处理抽奖的创建、参与、开奖和统计"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import Lottery, LotteryParticipant, LotteryWinner, TgUser
from bot.models.enums import PointsTxnType

log = structlog.get_logger(__name__)


# ==================== 数据类 ====================

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


# ==================== 抽奖管理 ====================

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


# ==================== 参与验证 ====================

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


# ==================== 开奖功能 ====================

async def create_lottery_winner(
    session: AsyncSession,
    lottery_id: int,
    user_id: int,
    prize_name: str,
    prize_index: int,
    points_reward: int = 0,
) -> LotteryWinner:
    """
    创建中奖记录

    Args:
        session: 数据库会话
        lottery_id: 抽奖ID
        user_id: 用户ID
        prize_name: 奖品名称
        prize_index: 奖品索引
        points_reward: 积分奖励

    Returns:
        创建的中奖记录对象
    """
    winner = LotteryWinner(
        lottery_id=lottery_id,
        user_id=user_id,
        prize_name=prize_name,
        prize_index=prize_index,
        points_reward=points_reward,
    )
    session.add(winner)
    await session.flush()
    return winner


async def perform_random_draw(
    session: AsyncSession,
    lottery: Lottery,
) -> list[LotteryWinner]:
    """
    执行随机开奖

    Args:
        session: 数据库会话
        lottery: 抽奖对象

    Returns:
        中奖者列表
    """
    # 获取所有参与者
    participants = await get_lottery_participants(session, lottery.id)
    if not participants:
        return []

    # 获取用户信息
    user_ids = [p.user_id for p in participants]
    stmt = select(TgUser).where(TgUser.id.in_(user_ids))
    result = await session.execute(stmt)
    users = {u.id: u for u in result.scalars().all()}

    # 构建奖品列表（展开数量）
    prize_list = []
    for prize in lottery.prizes:
        quantity = prize.get("quantity", 1)
        for _ in range(quantity):
            prize_list.append({
                "prize_index": len(prize_list),
                "name": prize["name"],
                "points_reward": prize.get("points_reward", 0),
            })

    if not prize_list:
        return []

    # 随机选择中奖者
    winners = []
    available_participants = participants.copy()
    random.shuffle(available_participants)

    for prize in prize_list:
        if not available_participants:
            break

        participant = available_participants.pop()
        user = users.get(participant.user_id)

        winner = LotteryWinner(
            lottery_id=lottery.id,
            user_id=participant.user_id,
            prize_name=prize["name"],
            prize_index=prize["prize_index"],
            points_reward=prize["points_reward"],
        )
        session.add(winner)
        winners.append(winner)

    await session.flush()
    return winners


def generate_lottery_announcement(
    lottery: Lottery,
    winners: list[LotteryWinner],
    users: dict[int, TgUser],
) -> str:
    """
    生成开奖公告（含@中奖用户）

    Args:
        lottery: 抽奖对象
        winners: 中奖者列表
        users: 用户信息字典

    Returns:
        开奖公告文本
    """
    text = f"🎉 抽奖【{lottery.title}】开奖结果\n\n"
    text += f"🎁 中奖名单：\n"

    for winner in winners:
        user = users.get(winner.user_id)
        if user:
            # 使用 mention 格式 @用户
            mention = f"[{user.full_name or user.username or '用户'}](tg://user?id={winner.user_id})"
            text += f"• {winner.prize_name}: {mention}"
            if winner.points_reward > 0:
                text += f" （+{winner.points_reward}积分）"
            text += "\n"
        else:
            text += f"• {winner.prize_name}: 用户{winner.user_id}\n"

    return text


async def distribute_lottery_rewards(
    session: AsyncSession,
    lottery: Lottery,
    winners: list[LotteryWinner],
) -> None:
    """
    发放中奖积分奖励

    Args:
        session: 数据库会话
        lottery: 抽奖对象
        winners: 中奖者列表
    """
    from bot.services.activity.points_service import change_points

    for winner in winners:
        if winner.points_reward > 0:
            # 发放积分
            success, new_balance = await change_points(
                session,
                lottery.chat_id,
                winner.user_id,
                winner.points_reward,
                PointsTxnType.lottery_win.value,
                f"抽奖【{lottery.title}】中奖奖励"
            )
            if not success:
                log.error(
                    "lottery_reward_failed",
                    lottery_id=lottery.id,
                    winner_id=winner.user_id,
                    reward_amount=winner.points_reward,
                )
