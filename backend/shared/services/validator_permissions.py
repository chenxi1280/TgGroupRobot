from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from telegram.ext import Application

log = structlog.get_logger(__name__)


async def validate_user_permission(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> bool:
    from backend.shared.services.permission_service import is_user_admin

    return await is_user_admin(app, chat_id, user_id)


async def validate_bot_permission(
    app: "Application",
    chat_id: int,
    required_permission: str,
) -> bool:
    try:
        bot = app.bot
        chat = await bot.get_chat(chat_id)
        bot_member = await chat.get_member(bot.id)

        if required_permission == "can_delete_messages":
            return bot_member.can_delete_messages
        if required_permission == "can_restrict_members":
            return bot_member.can_restrict_members
        if required_permission == "can_promote_members":
            return bot_member.can_promote_members
        if required_permission == "is_administrator":
            return bot_member.status in ["administrator", "creator"]
        return True
    except Exception as exc:
        log.warning(
            "validate_bot_permission_failed",
            chat_id=chat_id,
            required_permission=required_permission,
            error=str(exc),
        )
        return False


async def validate_user_in_group(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> bool:
    try:
        bot = app.bot
        chat = await bot.get_chat(chat_id)
        member = await chat.get_member(user_id)
        return member is not None
    except Exception as exc:
        log.warning("validate_user_membership_failed", chat_id=chat_id, user_id=user_id, error=str(exc))
        return False


async def validate_user_is_admin(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> tuple[bool, str | None]:
    is_admin = await validate_user_permission(app, chat_id, user_id)
    if is_admin:
        return True, None
    return False, "需要管理员权限"
