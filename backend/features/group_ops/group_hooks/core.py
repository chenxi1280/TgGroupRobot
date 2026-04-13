from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgUser
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import is_user_admin

from .controls import (
    _check_force_subscribe,
    _process_group_lock_controls,
    _process_new_member_limit,
    _process_night_mode,
    _process_rename_monitor,
)
from .garage import _process_garage_features
from .moderation import (
    _process_alliance_joint_ban,
    _process_alliance_reply_ban,
    _process_auto_reply,
    _process_banned_word_check,
)

log = structlog.get_logger(__name__)


async def unified_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    log.warning(
        "=== UNIFIED_GROUP_MESSAGE_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        message_text=(update.effective_message.text or update.effective_message.caption or "")[:50],
    )

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if chat.type == "private":
        return False

    message_text = message.text or message.caption or ""

    is_admin = False
    try:
        is_admin = await is_user_admin(context, chat.id, user.id)
    except Exception as exc:
        log.warning("admin_check_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    log.info(
        "unified_handler_admin_check",
        chat_id=chat.id,
        user_id=user.id,
        is_admin=is_admin,
    )

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        old_user = await session.get(TgUser, user.id)
        old_username = old_user.username if old_user else None
        old_name = " ".join(
            part
            for part in [old_user.first_name if old_user else None, old_user.last_name if old_user else None]
            if part
        ) if old_user else ""
        settings = await ModuleSettingsService.ensure(
            session,
            chat.id,
            chat_type=chat.type,
            title=chat.title,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        await session.commit()

    if await _process_rename_monitor(context, chat, user, settings, old_username, old_name):
        log.info("rename_monitor_processed", chat_id=chat.id, user_id=user.id)

    if await _process_group_lock_controls(context, chat, user, message, settings, is_admin, message_text):
        return True

    if await _process_night_mode(context, chat, user, message, settings, is_admin):
        return True

    if is_admin and await _process_alliance_reply_ban(context, db, chat, user, message, message_text):
        return True

    if not is_admin:
        if await _process_alliance_joint_ban(context, db, chat, user, message):
            return True
        if not await _check_force_subscribe(context, chat, user, message, settings):
            return True
        if await _process_new_member_limit(context, db, chat, user, message, settings):
            return True

    if await _process_garage_features(context, db, chat, user, message, message_text, settings, is_admin):
        return True

    if message_text:
        if not is_admin:
            deleted = await _process_banned_word_check(context, db, chat, user, message, message_text)
            if deleted:
                return True
        else:
            log.info("unified_handler_skip_banned_word_admin", chat_id=chat.id, user_id=user.id)

        await _process_auto_reply(context, db, chat, message, message_text)

    return False
