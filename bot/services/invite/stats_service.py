"""邀请统计服务 - 处理邀请统计和排行榜"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import InviteLink, InviteTracking, TgUser
from bot.models.enums import InviteLinkStatus


class InviteStats(NamedTuple):
    """邀请统计"""
    total_invites: int  # 总邀请人数
    active_links: int  # 活跃链接数
    total_links: int  # 总链接数
    link_limit: int | None  # 链接生成上限
    links_generated: int  # 已生成链接数


async def get_user_invite_stats(session: AsyncSession, chat_id: int, user_id: int) -> InviteStats:
    """
    获取用户的邀请统计

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        InviteStats: 邀请统计数据
    """
    from bot.models.core import ChatSettings

    # 获取用户创建的链接数
    link_result = await session.execute(
        select(func.count(InviteLink.id))
        .where(
            and_(
                InviteLink.chat_id == chat_id,
                InviteLink.created_by_user_id == user_id,
            )
        )
    )
    total_links = link_result.scalar() or 0

    # 获取活跃链接数
    active_result = await session.execute(
        select(func.count(InviteLink.id))
        .where(
            and_(
                InviteLink.chat_id == chat_id,
                InviteLink.created_by_user_id == user_id,
                InviteLink.status == InviteLinkStatus.active.value,
            )
        )
    )
    active_links = active_result.scalar() or 0

    # 获取总邀请人数
    invite_result = await session.execute(
        select(func.count(InviteTracking.id))
        .where(
            and_(
                InviteTracking.chat_id == chat_id,
                InviteTracking.inviter_user_id == user_id,
            )
        )
    )
    total_invites = invite_result.scalar() or 0

    # 获取群组配置的链接生成上限
    settings_result = await session.execute(
        select(ChatSettings.invite_link_user_limit).where(ChatSettings.chat_id == chat_id)
    )
    link_limit = settings_result.scalar()

    return InviteStats(
        total_invites=total_invites,
        active_links=active_links,
        total_links=total_links,
        link_limit=link_limit,
        links_generated=total_links,
    )


async def get_invite_leaderboard(session: AsyncSession, chat_id: int, limit: int = 10) -> list[tuple[int, int, str | None]]:
    """
    获取邀请排行榜

    Args:
        session: 数据库会话
        chat_id: 群组ID
        limit: 返回数量

    Returns:
        [(user_id, invite_count, username), ...] 按邀请数降序排列
    """
    result = await session.execute(
        select(
            InviteTracking.inviter_user_id,
            func.count(InviteTracking.id).label('invite_count'),
            TgUser.username,
        )
        .join(TgUser, InviteTracking.inviter_user_id == TgUser.id)
        .where(InviteTracking.chat_id == chat_id)
        .group_by(InviteTracking.inviter_user_id, TgUser.username)
        .order_by(func.count(InviteTracking.id).desc())
        .limit(limit)
    )
    return [(row.inviter_user_id, row.invite_count, row.username) for row in result]


async def get_user_rank(session: AsyncSession, chat_id: int, user_id: int) -> int | None:
    """
    获取用户在邀请榜的排名

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        排名（从1开始），如果没有邀请记录则返回 None
    """
    # 获取用户的邀请数
    user_result = await session.execute(
        select(func.count(InviteTracking.id))
        .where(
            and_(
                InviteTracking.chat_id == chat_id,
                InviteTracking.inviter_user_id == user_id,
            )
        )
    )
    user_count = user_result.scalar() or 0
    if user_count == 0:
        return None

    # 统计比该用户邀请数多的人数
    result = await session.execute(
        select(func.count(InviteTracking.inviter_user_id))
        .where(InviteTracking.chat_id == chat_id)
        .group_by(InviteTracking.inviter_user_id)
        .having(func.count(InviteTracking.id) > user_count)
    )
    more_count = len(result.all())
    return more_count + 1
