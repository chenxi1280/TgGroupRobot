"""抽奖服务 - 处理抽奖的创建、参与、开奖和统计"""

from __future__ import annotations

import datetime as dt
import random
import re
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import Lottery, LotteryParticipant, LotteryWinner, TgUser
from bot.models.expansion import EngagementChatStat, LotterySetting
from bot.models.enums import PointsTxnType
from bot.models.core import InviteTracking

log = structlog.get_logger(__name__)


# ==================== 数据类 ====================


@dataclass
class ParsedLotteryConfig:
    """解析后的抽奖配置"""
    lottery_type: str
    title: str
    description: str | None
    draw_time: dt.datetime
    min_points: int
    participation_cost: int
    max_participants: int
    requirement_days: int
    qualification_window_days: int
    required_invites: int
    required_activity_count: int
    finalist_limit: int
    selection_mode: str
    prizes: list[dict]


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
        "insufficient_invites",
        "insufficient_activity",
        "ranking_auto_selection",
        "max_participants_reached",
        "not_member_long_enough",
        "outside_join_time",
    ]


# ==================== 格式化函数 ====================


def format_lottery_stats_message(stats: dict[str, int]) -> str:
    """
    格式化抽奖统计消息

    Args:
        stats: 统计数据字典，包含 total, pending, completed, cancelled

    Returns:
        格式化后的抽奖统计消息文本
    """
    return (
        f"🎁 抽奖统计\n\n"
        f"创建的抽奖次数: {stats['total']}\n\n"
        f"已开奖: {stats['completed']}       未开奖: {stats['pending']}"
    )


def _lottery_type_label(lottery_type: str) -> str:
    return {
        "common": "🎁 通用抽奖",
        "points": "💰 积分抽奖",
        "invite": "👥 邀请抽奖",
        "activity": "🔥 群活跃抽奖",
    }.get(lottery_type, "🎁 抽奖")


# ==================== 配置解析 ====================


def parse_lottery_config_text(text: str, lottery_type: str = "common", selection_mode: str = "threshold_random") -> ParsedLotteryConfig:
    """
    解析抽奖配置文本

    Args:
        text: 配置文本

    Returns:
        ParsedLotteryConfig: 解析后的配置对象

    Raises:
        ValueError: 配置格式错误
    """
    lines = text.strip().split("\n")
    if len(lines) < 7:
        raise ValueError("配置格式不完整")

    # 解析标题和描述
    title_line = lines[0].strip()
    if "|" in title_line:
        title, description = title_line.split("|", 1)
        title = title.strip()
        description = description.strip()
    else:
        title = title_line.strip()
        description = None

    if not title:
        raise ValueError("标题不能为空")

    # 解析开奖时间
    draw_time_line = lines[1].strip()
    if not draw_time_line.startswith("开奖时间:"):
        raise ValueError("开奖时间格式错误，应为: 开奖时间: 2025-12-30 12:00")
    time_pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})"
    match = re.search(time_pattern, draw_time_line)
    if not match:
        raise ValueError("开奖时间格式错误，请使用: YYYY-MM-DD HH:MM")
    year, month, day, hour, minute = map(int, match.groups())
    local_tz = dt.timezone(dt.timedelta(hours=8))
    draw_time = dt.datetime(year, month, day, hour, minute, tzinfo=local_tz)
    draw_time_utc = draw_time.astimezone(dt.timezone.utc)

    if draw_time_utc <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("开奖时间必须是未来时间")

    # 解析参与条件
    min_points = 0
    participation_cost = 0
    max_participants = 0
    requirement_days = 0
    qualification_window_days = 0
    required_invites = 0
    required_activity_count = 0
    finalist_limit = 0

    for line in lines[2:]:
        line = line.strip()
        if not line or line == "奖品:":
            continue
        if line.startswith("最低积分:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                min_points = max(0, value)
            except ValueError:
                raise ValueError("最低积分必须是有效数字")
        elif line.startswith("参与费用:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                participation_cost = max(0, value)
            except ValueError:
                raise ValueError("参与费用必须是有效数字")
        elif line.startswith("最大人数:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                max_participants = max(0, value)
            except ValueError:
                raise ValueError("最大人数必须是有效数字")
        elif line.startswith("入群天数:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                requirement_days = max(0, value)
            except ValueError:
                raise ValueError("入群天数必须是有效数字")
        elif line.startswith("邀请人数:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                required_invites = max(0, value)
            except ValueError:
                raise ValueError("邀请人数必须是有效数字")
        elif line.startswith("活跃消息数:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                required_activity_count = max(0, value)
            except ValueError:
                raise ValueError("活跃消息数必须是有效数字")
        elif line.startswith("统计天数:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                qualification_window_days = max(0, value)
            except ValueError:
                raise ValueError("统计天数必须是有效数字")
        elif line.startswith("入围人数:"):
            try:
                value = int(line.split(":", 1)[1].strip())
                finalist_limit = max(0, value)
            except ValueError:
                raise ValueError("入围人数必须是有效数字")

    # 解析奖品
    prizes = []
    prize_start = False
    for line in lines[6:]:
        line = line.strip()
        if line == "奖品:":
            prize_start = True
            continue
        if prize_start and line:
            parts = line.split(",")
            if len(parts) < 2:
                raise ValueError(f"奖品格式错误: {line}")

            prize_name = parts[0].strip()
            quantity = int(parts[1].strip())
            points_reward = 0

            # 支持第三个参数：积分奖励
            if len(parts) >= 3:
                try:
                    points_reward = int(parts[2].strip().replace("积分", "").strip())
                except ValueError:
                    raise ValueError(f"积分奖励格式错误: {parts[2]}")

            prizes.append({"name": prize_name, "quantity": quantity, "points_reward": points_reward})

    if not prizes:
        raise ValueError("至少需要一个奖品")

    if lottery_type == "invite" and required_invites <= 0:
        raise ValueError("邀请抽奖必须配置邀请人数，格式如：邀请人数: 3")
    if lottery_type == "activity" and required_activity_count <= 0:
        raise ValueError("群活跃抽奖必须配置活跃消息数，格式如：活跃消息数: 200")
    if lottery_type in {"invite", "activity"} and qualification_window_days <= 0:
        qualification_window_days = 7
    if selection_mode == "ranking_random" and finalist_limit <= 0:
        raise ValueError("排名入围随机玩法必须配置入围人数，格式如：入围人数: 10")

    return ParsedLotteryConfig(
        lottery_type=lottery_type,
        title=title,
        description=description,
        draw_time=draw_time_utc,
        min_points=min_points,
        participation_cost=participation_cost,
        max_participants=max_participants,
        requirement_days=requirement_days,
        qualification_window_days=qualification_window_days,
        required_invites=required_invites,
        required_activity_count=required_activity_count,
        finalist_limit=finalist_limit,
        selection_mode=selection_mode,
        prizes=prizes,
    )


def format_lottery_announcement_text(config: ParsedLotteryConfig) -> str:
    """
    格式化抽奖公告文本

    Args:
        config: 解析后的抽奖配置

    Returns:
        格式化后的公告文本
    """
    text = f"{_lottery_type_label(config.lottery_type)}\n\n"
    text += f"📢 {config.title}"
    if config.description:
        text += f"\n\n{config.description}"
    text += f"\n\n🕐 开奖时间: {config.draw_time.strftime('%Y-%m-%d %H:%M')}"
    if config.min_points > 0:
        text += f"\n💰 最低积分: {config.min_points}"
    if config.participation_cost > 0:
        text += f"\n💸 参与费用: {config.participation_cost} 积分"
    if config.required_invites > 0:
        text += f"\n👥 邀请人数门槛: {config.required_invites}"
    if config.required_activity_count > 0:
        text += f"\n🔥 活跃消息门槛: {config.required_activity_count}"
    if config.qualification_window_days > 0:
        text += f"\n📊 统计天数: 最近 {config.qualification_window_days} 天"
    if config.selection_mode == "ranking_random" and config.finalist_limit > 0:
        text += f"\n🏆 排名入围人数: 前 {config.finalist_limit} 名"
    if config.max_participants > 0:
        text += f"\n👥 最大人数: {config.max_participants}"
    if config.requirement_days > 0:
        text += f"\n📅 入群天数: {config.requirement_days}"
    text += f"\n\n🎁 奖品:"
    for prize in config.prizes:
        text += f"\n  • {prize['name']} x {prize['quantity']}"
    if config.selection_mode == "ranking_random":
        text += "\n\n💡 本玩法会在开奖时按排行自动生成入围名单，再随机开奖。"
    else:
        text += f"\n\n💡 点击下方按钮参与抽奖！"
    return text


# ==================== 抽奖管理 ====================

async def create_lottery(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    title: str,
    draw_time: dt.datetime,
    prizes: list[dict],
    description: str | None = None,
    lottery_type: str = "common",
    qualification_rules: dict | None = None,
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
        lottery_type=lottery_type,
        draw_time=draw_time,
        prizes=prizes,
        status="pending",
        qualification_rules=qualification_rules or {},
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


async def get_or_create_lottery_setting(session: AsyncSession, chat_id: int) -> LotterySetting:
    setting = await session.get(LotterySetting, chat_id)
    if setting is None:
        setting = LotterySetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_lottery_setting(session: AsyncSession, chat_id: int, **updates) -> LotterySetting:
    setting = await get_or_create_lottery_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    await session.flush()
    return setting


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
    lottery_type: str | None = None,
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
    if lottery_type and lottery_type != "all":
        stmt = stmt.where(Lottery.lottery_type == lottery_type)
    stmt = stmt.order_by(Lottery.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_lotteries_by_type(session: AsyncSession, chat_id: int) -> dict[str, int]:
    stmt = (
        select(Lottery.lottery_type, func.count(Lottery.id))
        .where(Lottery.chat_id == chat_id)
        .group_by(Lottery.lottery_type)
    )
    result = await session.execute(stmt)
    counts = {"common": 0, "points": 0, "invite": 0, "activity": 0}
    for lottery_type, count in result.all():
        counts[lottery_type] = int(count)
    return counts


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
                since = now - dt.timedelta(days=window_days)
                invite_stmt = invite_stmt.where(InviteTracking.joined_at >= since)
            invite_result = await session.execute(invite_stmt)
            invite_count = int(invite_result.scalar() or 0)
            if invite_count < required_invites:
                return JoinResult(success=False, reason="insufficient_invites")

    if lottery.lottery_type == "activity":
        required_activity = int(qualification_rules.get("required_activity_count") or 0)
        if required_activity > 0:
            activity_stmt = select(func.coalesce(func.sum(EngagementChatStat.message_count), 0)).where(
                EngagementChatStat.chat_id == lottery.chat_id,
                EngagementChatStat.user_id == user_id,
            )
            if window_days > 0:
                since_date = (now - dt.timedelta(days=window_days)).date()
                activity_stmt = activity_stmt.where(EngagementChatStat.biz_date >= since_date)
            activity_result = await session.execute(activity_stmt)
            message_count = int(activity_result.scalar() or 0)
            if message_count < required_activity:
                return JoinResult(success=False, reason="insufficient_activity")

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


async def build_ranked_finalists(session: AsyncSession, lottery: Lottery) -> list[LotteryParticipant]:
    qualification_rules = lottery.qualification_rules or {}
    finalist_limit = max(int(qualification_rules.get("finalist_limit") or 0), 0)
    window_days = max(int(qualification_rules.get("window_days") or 0), 0)
    required_invites = max(int(qualification_rules.get("required_invites") or 0), 0)
    required_activity = max(int(qualification_rules.get("required_activity_count") or 0), 0)
    if finalist_limit <= 0:
        return []

    now = dt.datetime.now(dt.timezone.utc)
    user_ids: list[int] = []
    if lottery.lottery_type == "invite":
        stmt = (
            select(InviteTracking.inviter_user_id, func.count(InviteTracking.id).label("cnt"))
            .where(
                InviteTracking.chat_id == lottery.chat_id,
                InviteTracking.inviter_user_id.is_not(None),
            )
            .group_by(InviteTracking.inviter_user_id)
            .order_by(func.count(InviteTracking.id).desc(), InviteTracking.inviter_user_id.asc())
            .limit(finalist_limit)
        )
        if window_days > 0:
            stmt = stmt.where(InviteTracking.joined_at >= now - dt.timedelta(days=window_days))
        result = await session.execute(stmt)
        user_ids = [int(row[0]) for row in result.all() if row[0] is not None and int(row[1] or 0) >= required_invites]
    elif lottery.lottery_type == "activity":
        since_date = (now - dt.timedelta(days=window_days)).date() if window_days > 0 else None
        stmt = (
            select(EngagementChatStat.user_id, func.coalesce(func.sum(EngagementChatStat.message_count), 0).label("cnt"))
            .where(EngagementChatStat.chat_id == lottery.chat_id)
            .group_by(EngagementChatStat.user_id)
            .order_by(func.sum(EngagementChatStat.message_count).desc(), EngagementChatStat.user_id.asc())
            .limit(finalist_limit)
        )
        if since_date is not None:
            stmt = stmt.where(EngagementChatStat.biz_date >= since_date)
        result = await session.execute(stmt)
        user_ids = [int(row[0]) for row in result.all() if int(row[1] or 0) >= required_activity]

    finalists: list[LotteryParticipant] = []
    for user_id in user_ids:
        bal = 0
        existing = LotteryParticipant(lottery_id=lottery.id, user_id=user_id, points_balance=bal)
        finalists.append(existing)
    return finalists


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
    qualification_rules = lottery.qualification_rules or {}
    if qualification_rules.get("selection_mode") == "ranking_random" and lottery.lottery_type in {"invite", "activity"}:
        participants = await build_ranked_finalists(session, lottery)
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
    text = f"🎉 {_lottery_type_label(lottery.lottery_type)}【{lottery.title}】开奖结果\n\n"
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
