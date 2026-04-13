"""邀请链接服务 - 兼容导出与敏感入口 wrapper。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from backend.features.invite.services.invite_links import *  # noqa: F401,F403
from backend.features.invite.services.invite_mutations import (
    delete_invite_link_impl,
    revoke_invite_link_impl,
    update_invite_link_info_impl,
)
from backend.features.invite.services.invite_stats import *  # noqa: F401,F403
from backend.features.invite.services.invite_tracking import *  # noqa: F401,F403
from backend.features.invite.services.invite_types import *  # noqa: F401,F403


async def revoke_invite_link(
    session: AsyncSession,
    bot: Bot,
    link_id: int,
    *,
    chat_id: int | None = None,
) -> RevokeResult:
    return await revoke_invite_link_impl(
        session,
        bot,
        link_id,
        chat_id=chat_id,
        scoped_lookup=get_invite_link_in_chat,
    )


async def update_invite_link_info(
    session: AsyncSession,
    bot: Bot,
    link_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    return await update_invite_link_info_impl(
        session,
        bot,
        link_id,
        chat_id=chat_id,
        scoped_lookup=get_invite_link_in_chat,
    )


async def delete_invite_link(
    session: AsyncSession,
    link_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    return await delete_invite_link_impl(
        session,
        link_id,
        chat_id=chat_id,
        scoped_lookup=get_invite_link_in_chat,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
