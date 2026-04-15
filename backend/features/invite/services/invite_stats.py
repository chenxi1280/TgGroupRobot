from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.invite.services.invite_links import get_chat_invite_links
from backend.features.invite.services.invite_types import InviteStats
from backend.platform.db.schema.models.core import ChatSettings, InviteLink, InviteTracking, TgUser
from backend.platform.db.schema.models.enums import InviteLinkStatus


async def get_link_stats(session: AsyncSession, chat_id: int) -> dict[str, int]:
    """获取邀请链接统计"""
    links = await get_chat_invite_links(session, chat_id)
    invite_result = await session.execute(
        select(func.count(InviteTracking.id)).where(InviteTracking.chat_id == chat_id)
    )
    total_invites = int(invite_result.scalar() or 0)
    return {
        "total": len(links),
        "active": sum(1 for l in links if l.status == InviteLinkStatus.active.value),
        "revoked": sum(1 for l in links if l.status == InviteLinkStatus.revoked.value),
        "expired": sum(1 for l in links if l.status == InviteLinkStatus.expired.value),
        "total_members": sum(l.member_count for l in links),
        "total_invites": total_invites,
    }


async def get_user_invite_stats(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> InviteStats:
    """获取用户的邀请统计"""
    link_result = await session.execute(
        select(func.count(InviteLink.id)).where(
            and_(
                InviteLink.chat_id == chat_id,
                InviteLink.created_by_user_id == user_id,
            )
        )
    )
    total_links = link_result.scalar() or 0

    active_result = await session.execute(
        select(func.count(InviteLink.id)).where(
            and_(
                InviteLink.chat_id == chat_id,
                InviteLink.created_by_user_id == user_id,
                InviteLink.status == InviteLinkStatus.active.value,
            )
        )
    )
    active_links = active_result.scalar() or 0

    invite_result = await session.execute(
        select(func.count(InviteTracking.id)).where(
            and_(
                InviteTracking.chat_id == chat_id,
                InviteTracking.inviter_user_id == user_id,
            )
        )
    )
    total_invites = invite_result.scalar() or 0

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


async def get_invite_leaderboard(
    session: AsyncSession,
    chat_id: int,
    limit: int = 10,
) -> list[tuple[int, int, str | None]]:
    """获取邀请排行榜"""
    result = await session.execute(
        select(
            InviteTracking.inviter_user_id,
            func.count(InviteTracking.id).label("invite_count"),
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
    user_result = await session.execute(
        select(func.count(InviteTracking.id)).where(
            and_(
                InviteTracking.chat_id == chat_id,
                InviteTracking.inviter_user_id == user_id,
            )
        )
    )
    user_count = user_result.scalar() or 0
    if user_count == 0:
        return None

    result = await session.execute(
        select(func.count(InviteTracking.inviter_user_id))
        .where(InviteTracking.chat_id == chat_id)
        .group_by(InviteTracking.inviter_user_id)
        .having(func.count(InviteTracking.id) > user_count)
    )
    more_count = len(result.all())
    return more_count + 1
