from __future__ import annotations

import csv
import io

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.invite.services.invite_links import get_chat_invite_links
from backend.platform.db.schema.models.core import ChatSettings, InviteTracking, TgUser


async def clear_invite_counts(session: AsyncSession, chat_id: int) -> int:
    result = await session.execute(delete(InviteTracking).where(InviteTracking.chat_id == chat_id))
    links = await get_chat_invite_links(session, chat_id)
    for link in links:
        link.member_count = 0
    await session.flush()
    return int(result.rowcount or 0)


async def clear_chat_invite_links(session: AsyncSession, chat_id: int):
    links = await get_chat_invite_links(session, chat_id)
    for link in links:
        await session.delete(link)
    await session.flush()
    return links


async def export_invite_tracking_csv(session: AsyncSession, chat_id: int) -> tuple[str, bytes]:
    result = await session.execute(
        select(
            InviteTracking.inviter_user_id,
            InviteTracking.invited_user_id,
            InviteTracking.points_awarded,
            InviteTracking.joined_at,
            TgUser.username,
        )
        .join(TgUser, InviteTracking.inviter_user_id == TgUser.id)
        .where(InviteTracking.chat_id == chat_id)
        .order_by(InviteTracking.joined_at.desc())
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["inviter_user_id", "inviter_username", "invitee_user_id", "points_awarded", "joined_at"])
    for row in result:
        writer.writerow(
            [
                row.inviter_user_id,
                row.username or "",
                row.invited_user_id,
                int(bool(row.points_awarded)),
                row.joined_at.isoformat() if row.joined_at else "",
            ]
        )
    filename = f"invite_export_{chat_id}.csv"
    return filename, buffer.getvalue().encode("utf-8")


async def track_and_award_invite(
    session: AsyncSession,
    chat_id: int,
    inviter_user_id: int,
    *, invited_user_id: int,
    invite_link_id: int | None = None,
) -> tuple[bool, bool, str | None]:
    """追踪邀请并发放积分"""
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
        return False, False, None

    tracking = InviteTracking(
        chat_id=chat_id,
        inviter_user_id=inviter_user_id,
        invited_user_id=invited_user_id,
        invite_link_id=invite_link_id,
        points_awarded=False,
    )
    session.add(tracking)
    await session.flush()

    settings_result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    settings = settings_result.scalar_one_or_none()

    if not settings or not settings.invite_points_enabled or not settings.invite_points or settings.invite_points <= 0:
        return True, False, None

    from backend.features.points.services.points_service import add_invite_points

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
    return True, False, result.reason
