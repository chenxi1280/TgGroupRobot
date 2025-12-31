from __future__ import annotations

import datetime as dt
from typing import NamedTuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from bot.models.core import InviteLink, InviteTracking, TgChat, TgUser
from bot.models.enums import InviteLinkStatus


class InviteStats(NamedTuple):
    """邀请统计"""
    total_invites: int  # 总邀请人数
    active_links: int  # 活跃链接数
    total_links: int  # 总链接数
    link_limit: int | None  # 链接生成上限
    links_generated: int  # 已生成链接数


async def get_user_invite_stats(session: AsyncSession, chat_id: int, user_id: int) -> InviteStats:
    """获取用户的邀请统计"""
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
    from bot.models.core import ChatSettings
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


async def get_user_links(session: AsyncSession, chat_id: int, user_id: int) -> list[InviteLink]:
    """获取用户创建的所有链接"""
    result = await session.execute(
        select(InviteLink)
        .where(
            and_(
                InviteLink.chat_id == chat_id,
                InviteLink.created_by_user_id == user_id,
            )
        )
        .order_by(InviteLink.created_at.desc())
    )
    return list(result.scalars().all())


async def can_create_link(session: AsyncSession, chat_id: int, user_id: int) -> tuple[bool, str | None]:
    """检查用户是否可以创建新链接"""
    from bot.models.core import ChatSettings

    # 检查群组设置
    settings_result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    settings = settings_result.scalar_one_or_none()
    if not settings or not settings.invite_link_enabled:
        return False, "本群未开启邀请链接功能"

    # 检查用户已创建的链接数
    count_result = await session.execute(
        select(func.count(InviteLink.id))
        .where(
            and_(
                InviteLink.chat_id == chat_id,
                InviteLink.created_by_user_id == user_id,
                InviteLink.status == InviteLinkStatus.active.value,
            )
        )
    )
    active_count = count_result.scalar() or 0

    if settings.invite_link_user_limit is not None and active_count >= settings.invite_link_user_limit:
        return False, f"您已达到链接生成上限（{settings.invite_link_user_limit}个）"

    return True, None


async def create_invite_link(
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    user_id: int,
    name: str | None = None,
) -> tuple[bool, InviteLink | None, str | None]:
    """创建邀请链接"""
    # 检查是否可以创建
    can_create, error_msg = await can_create_link(session, chat_id, user_id)
    if not can_create:
        return False, None, error_msg

    from bot.models.core import ChatSettings

    settings_result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    settings = settings_result.scalar_one_or_none()
    if not settings:
        return False, None, "群组设置不存在"

    # 计算过期时间
    expire_date = None
    if settings.invite_link_expire_days is not None:
        expire_date = dt.datetime.now(dt.UTC) + dt.timedelta(days=settings.invite_link_expire_days)

    try:
        # 创建 Telegram 邀请链接
        chat = await bot.get_chat(chat_id)

        # 准备创建链接的参数
        create_kwargs = {
            "member_limit": settings.invite_link_max_joins,
            "creates_join_request": False,
        }
        if expire_date:
            create_kwargs["expire_date"] = expire_date

        invite = await chat.create_invite_link(**create_kwargs)

        # 保存到数据库
        link = InviteLink(
            chat_id=chat_id,
            created_by_user_id=user_id,
            invite_link=invite.invite_link,
            name=name,
            status=InviteLinkStatus.active.value,
            member_limit=settings.invite_link_max_joins,
            expire_date=expire_date,
        )
        session.add(link)
        await session.flush()

        return True, link, None
    except Exception as e:
        return False, None, f"创建链接失败: {str(e)}"


async def get_invite_leaderboard(session: AsyncSession, chat_id: int, limit: int = 10) -> list[tuple[int, int, str | None]]:
    """获取邀请排行榜"""
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
    """获取用户在邀请榜的排名"""
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


async def track_and_award_invite(
    session: AsyncSession,
    chat_id: int,
    inviter_user_id: int,
    invited_user_id: int,
    invite_link_id: int | None = None,
) -> tuple[bool, bool, str | None]:
    """
    追踪邀请并发放积分

    Returns:
        (is_new_invite, points_awarded, error_message)
    """
    from bot.models.core import ChatSettings

    # 检查是否已经追踪过这个邀请（防止重复计算）
    existing_result = await session.execute(
        select(InviteTracking).where(
            and_(
                InviteTracking.chat_id == chat_id,
                InviteTracking.invited_user_id == invited_user_id,
            )
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        # 已经被追踪过，不是新邀请
        return False, False, None

    # 创建新的邀请追踪记录
    tracking = InviteTracking(
        chat_id=chat_id,
        inviter_user_id=inviter_user_id,
        invited_user_id=invited_user_id,
        invite_link_id=invite_link_id,
        points_awarded=False,
    )
    session.add(tracking)
    await session.flush()

    # 获取群组设置
    settings_result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    settings = settings_result.scalar_one_or_none()

    if not settings or not settings.invite_points_enabled or not settings.invite_points or settings.invite_points <= 0:
        # 没有启用邀请积分
        return True, False, None

    # 发放积分
    from bot.services.points_service import add_invite_points

    result = await add_invite_points(
        session,
        chat_id=chat_id,
        inviter_user_id=inviter_user_id,
        points=settings.invite_points,
        daily_limit=settings.invite_points_daily_limit,
    )

    if result.success:
        tracking.points_awarded = True
        return True, True, None
    else:
        # 积分发放失败（可能达到每日上限）
        return True, False, result.reason


async def clear_invite_data(session: AsyncSession, chat_id: int) -> int:
    """清空群组的所有邀请数据"""
    # 删除所有邀请追踪记录
    result = await session.execute(
        select(func.count(InviteTracking.id)).where(InviteTracking.chat_id == chat_id)
    )
    count = result.scalar() or 0

    await session.execute(
        select(InviteTracking).where(InviteTracking.chat_id == chat_id)
    )
    # 执行删除
    from sqlalchemy import delete
    await session.execute(
        delete(InviteTracking).where(InviteTracking.chat_id == chat_id)
    )

    return count
