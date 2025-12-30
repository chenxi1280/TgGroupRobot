from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from bot.models.core import InviteLink
from bot.models.enums import InviteLinkStatus


@dataclass
class CreateResult:
    """创建邀请链接结果"""
    success: bool
    reason: Literal["ok", "error", "limit_reached", "permission_denied"]
    invite_link: InviteLink | None = None


@dataclass
class RevokeResult:
    """撤销邀请链接结果"""
    success: bool
    reason: Literal["ok", "not_found", "already_revoked", "error"]


async def create_invite_link(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    bot: Bot,
    name: str | None = None,
    member_limit: int | None = None,
    expire_date: dt.datetime | None = None,
    creates_join_request: bool = False,
) -> CreateResult:
    """创建邀请链接"""
    try:
        # 调用 Telegram API 创建邀请链接
        chat_invite_link = await bot.create_chat_invite_link(
            chat_id=chat_id,
            name=name,
            member_limit=member_limit,
            expire_date=expire_date,
            creates_join_request=creates_join_request,
        )

        invite_link = InviteLink(
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            invite_link=chat_invite_link.invite_link,
            name=chat_invite_link.name,
            member_limit=chat_invite_link.member_limit,
            member_count=0,
            expire_date=chat_invite_link.expire_date,
            creates_join_request=chat_invite_link.creates_join_request,
            status=InviteLinkStatus.active.value,
        )
        session.add(invite_link)
        await session.flush()
        return CreateResult(success=True, reason="ok", invite_link=invite_link)

    except Exception as e:
        error_msg = str(e).lower()
        if "limit" in error_msg or "reached" in error_msg:
            return CreateResult(success=False, reason="limit_reached")
        elif "permission" in error_msg or "admin" in error_msg or "rights" in error_msg:
            return CreateResult(success=False, reason="permission_denied")
        return CreateResult(success=False, reason="error")


async def get_chat_invite_links(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[InviteLink]:
    """获取群组的邀请链接列表"""
    stmt = select(InviteLink).where(InviteLink.chat_id == chat_id)
    if active_only:
        stmt = stmt.where(InviteLink.status == InviteLinkStatus.active.value)
    stmt = stmt.order_by(InviteLink.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_invite_link(
    session: AsyncSession,
    link_id: int,
) -> InviteLink | None:
    """获取邀请链接"""
    stmt = select(InviteLink).where(InviteLink.id == link_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_invite_link(
    session: AsyncSession,
    bot: Bot,
    link_id: int,
) -> RevokeResult:
    """撤销邀请链接"""
    invite_link = await get_invite_link(session, link_id)
    if not invite_link:
        return RevokeResult(success=False, reason="not_found")

    if invite_link.status != InviteLinkStatus.active.value:
        return RevokeResult(success=False, reason="already_revoked")

    try:
        # 调用 Telegram API 撤销邀请链接
        await bot.revoke_chat_invite_link(chat_id=invite_link.chat_id, invite_link=invite_link.invite_link)
        invite_link.status = InviteLinkStatus.revoked.value
        return RevokeResult(success=True, reason="ok")
    except Exception as e:
        return RevokeResult(success=False, reason="error")


async def update_invite_link_info(
    session: AsyncSession,
    bot: Bot,
    link_id: int,
) -> bool:
    """更新邀请链接信息（从 Telegram 获取最新状态）"""
    invite_link = await get_invite_link(session, link_id)
    if not invite_link:
        return False

    try:
        # 获取邀请链接信息
        chat_invite_link = await bot.get_chat_invite_link(chat_id=invite_link.chat_id, invite_link=invite_link.invite_link)

        invite_link.member_count = chat_invite_link.member_count
        invite_link.expire_date = chat_invite_link.expire_date
        invite_link.creates_join_request = chat_invite_link.creates_join_request

        # 检查是否过期
        if chat_invite_link.expire_date and chat_invite_link.expire_date < dt.datetime.now(dt.UTC):
            invite_link.status = InviteLinkStatus.expired.value

        return True
    except Exception:
        # 如果链接已失效，标记为过期
        if invite_link:
            invite_link.status = InviteLinkStatus.expired.value
        return True


async def delete_invite_link(
    session: AsyncSession,
    link_id: int,
) -> bool:
    """删除邀请链接记录"""
    invite_link = await get_invite_link(session, link_id)
    if not invite_link:
        return False
    await session.delete(invite_link)
    return True


async def get_link_stats(
    session: AsyncSession,
    chat_id: int,
) -> dict[str, int]:
    """获取邀请链接统计"""
    links = await get_chat_invite_links(session, chat_id)
    return {
        "total": len(links),
        "active": sum(1 for l in links if l.status == InviteLinkStatus.active.value),
        "revoked": sum(1 for l in links if l.status == InviteLinkStatus.revoked.value),
        "expired": sum(1 for l in links if l.status == InviteLinkStatus.expired.value),
        "total_members": sum(l.member_count for l in links),
    }
