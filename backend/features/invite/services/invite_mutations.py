from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from backend.features.invite.services.invite_links import get_invite_link, get_invite_link_in_chat
from backend.features.invite.services.invite_types import RevokeResult
from backend.platform.db.schema.models.core import InviteLink
from backend.platform.db.schema.models.enums import InviteLinkStatus

InviteLinkLookup = Callable[[AsyncSession, int, int], Awaitable[InviteLink | None]]


async def revoke_invite_link_impl(
    session: AsyncSession,
    bot: Bot,
    link_id: int,
    *,
    chat_id: int | None = None,
    scoped_lookup: InviteLinkLookup = get_invite_link_in_chat,
) -> RevokeResult:
    """撤销邀请链接"""
    invite_link = await (
        scoped_lookup(session, chat_id, link_id)
        if chat_id is not None
        else get_invite_link(session, link_id)
    )
    if not invite_link:
        return RevokeResult(success=False, reason="not_found")

    if invite_link.status != InviteLinkStatus.active.value:
        return RevokeResult(success=False, reason="already_revoked")

    try:
        await bot.revoke_chat_invite_link(chat_id=invite_link.chat_id, invite_link=invite_link.invite_link)
        invite_link.status = InviteLinkStatus.revoked.value
        return RevokeResult(success=True, reason="ok")
    except Exception:
        return RevokeResult(success=False, reason="error")


async def update_invite_link_info_impl(
    session: AsyncSession,
    bot: Bot,
    link_id: int,
    *,
    chat_id: int | None = None,
    scoped_lookup: InviteLinkLookup = get_invite_link_in_chat,
) -> bool:
    """更新邀请链接信息（从 Telegram 获取最新状态）"""
    invite_link = await (
        scoped_lookup(session, chat_id, link_id)
        if chat_id is not None
        else get_invite_link(session, link_id)
    )
    if not invite_link:
        return False

    try:
        chat_invite_link = await bot.get_chat_invite_link(
            chat_id=invite_link.chat_id,
            invite_link=invite_link.invite_link,
        )
        invite_link.member_count = chat_invite_link.member_count
        invite_link.expire_date = chat_invite_link.expire_date
        invite_link.creates_join_request = chat_invite_link.creates_join_request

        if chat_invite_link.expire_date and chat_invite_link.expire_date < dt.datetime.now(dt.UTC):
            invite_link.status = InviteLinkStatus.expired.value

        return True
    except Exception:
        if invite_link:
            invite_link.status = InviteLinkStatus.expired.value
        return True


async def delete_invite_link_impl(
    session: AsyncSession,
    link_id: int,
    *,
    chat_id: int | None = None,
    scoped_lookup: InviteLinkLookup = get_invite_link_in_chat,
) -> bool:
    """删除邀请链接记录"""
    invite_link = await (
        scoped_lookup(session, chat_id, link_id)
        if chat_id is not None
        else get_invite_link(session, link_id)
    )
    if not invite_link:
        return False
    await session.delete(invite_link)
    return True
