"""邀请链接管理服务 - 合并自 invite_service 和 invite_link_service"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from bot.models.core import ChatSettings, InviteLink
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


async def can_create_link(session: AsyncSession, chat_id: int, user_id: int) -> tuple[bool, str | None]:
    """
    检查用户是否可以创建新链接

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        (是否可以创建, 错误信息)
    """
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
    chat_id: int,
    created_by_user_id: int,
    bot: Bot,
    name: str | None = None,
    member_limit: int | None = None,
    expire_date: dt.datetime | None = None,
    creates_join_request: bool = False,
) -> CreateResult:
    """
    创建邀请链接（管理员专用）

    Args:
        session: 数据库会话
        chat_id: 群组ID
        created_by_user_id: 创建者用户ID
        bot: Telegram Bot 实例
        name: 链接名称
        member_limit: 成员数量限制
        expire_date: 过期时间
        creates_join_request: 是否需要审批

    Returns:
        CreateResult: 创建结果
    """
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


async def create_user_invite_link(
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    user_id: int,
    name: str | None = None,
) -> tuple[bool, InviteLink | None, str | None]:
    """
    用户创建邀请链接（使用群组配置）

    Args:
        session: 数据库会话
        bot: Telegram Bot 实例
        chat_id: 群组ID
        user_id: 用户ID
        name: 链接名称

    Returns:
        (是否成功, 邀请链接对象, 错误信息)
    """
    # 检查是否可以创建
    can_create, error_msg = await can_create_link(session, chat_id, user_id)
    if not can_create:
        return False, None, error_msg

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
            "name": name,
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
