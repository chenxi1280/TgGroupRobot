from __future__ import annotations

import datetime as dt
import structlog

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from backend.features.invite.services.invite_types import CreateResult
from backend.platform.db.schema.models.core import ChatSettings, InviteLink
from backend.platform.db.schema.models.enums import InviteLinkStatus

log = structlog.get_logger(__name__)


async def can_create_link(session: AsyncSession, chat_id: int, user_id: int) -> tuple[bool, str | None]:
    """检查用户是否可以创建新链接"""
    settings_result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    settings = settings_result.scalar_one_or_none()
    if not settings or not settings.invite_link_enabled:
        return False, "本群未开启邀请链接功能"

    count_result = await session.execute(
        select(func.count(InviteLink.id)).where(
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
    *, bot: Bot,
    name: str | None = None,
    member_limit: int | None = None,
    expire_date: dt.datetime | None = None,
    creates_join_request: bool = False,
) -> CreateResult:
    """创建邀请链接（管理员专用）"""
    try:
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
        log.error("create_invite_link_failed", chat_id=chat_id, error=str(e))
        error_msg = str(e).lower()
        if "limit" in error_msg or "reached" in error_msg:
            return CreateResult(success=False, reason="limit_reached")
        if "permission" in error_msg or "admin" in error_msg or "rights" in error_msg:
            return CreateResult(success=False, reason="permission_denied")
        return CreateResult(success=False, reason="error")


async def create_user_invite_link(
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    *, user_id: int,
    name: str | None = None,
) -> tuple[bool, InviteLink | None, str | None]:
    """用户创建邀请链接（使用群组配置）"""
    can_create, error_msg = await can_create_link(session, chat_id, user_id)
    if not can_create:
        return False, None, error_msg

    settings_result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    settings = settings_result.scalar_one_or_none()
    if not settings:
        return False, None, "群组设置不存在"

    expire_date = None
    if settings.invite_link_expire_days is not None and settings.invite_link_expire_days > 0:
        expire_date = dt.datetime.now(dt.UTC) + dt.timedelta(days=settings.invite_link_expire_days)

    try:
        chat = await bot.get_chat(chat_id)
        create_kwargs = {
            "name": name,
            "member_limit": settings.invite_link_max_joins,
            "creates_join_request": settings.invite_link_mode == "relay",
        }
        if expire_date:
            create_kwargs["expire_date"] = expire_date

        invite = await chat.create_invite_link(**create_kwargs)

        link = InviteLink(
            chat_id=chat_id,
            created_by_user_id=user_id,
            invite_link=invite.invite_link,
            name=getattr(invite, "name", None) or name,
            status=InviteLinkStatus.active.value,
            member_limit=settings.invite_link_max_joins,
            member_count=0,
            expire_date=expire_date,
            creates_join_request=bool(getattr(invite, "creates_join_request", settings.invite_link_mode == "relay")),
        )
        session.add(link)
        await session.flush()

        return True, link, None
    except Exception as e:
        log.error("create_user_invite_link_failed", chat_id=chat_id, user_id=user_id, error=str(e))
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


async def get_invite_link(session: AsyncSession, link_id: int) -> InviteLink | None:
    """获取邀请链接"""
    stmt = select(InviteLink).where(InviteLink.id == link_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_invite_link_in_chat(
    session: AsyncSession,
    chat_id: int,
    link_id: int,
) -> InviteLink | None:
    """按群组作用域获取邀请链接，避免跨群访问。"""
    stmt = select(InviteLink).where(
        InviteLink.id == link_id,
        InviteLink.chat_id == chat_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
