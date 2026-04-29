from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgUser
from backend.platform.telegram.message_actor import build_sender_chat_actor, is_sender_chat_actor, resolve_message_actor
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import is_user_admin
from backend.features.group_ops.text_trigger_runtime import try_bottom_button_text_trigger

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


def _is_reserved_activity_trigger(message_text: str) -> bool:
    normalized = "".join(
        char
        for char in message_text
        if not char.isspace() and char not in {"\u200b", "\u200c", "\u200d", "\ufeff"}
    )
    if normalized.startswith("💰"):
        normalized = normalized[1:]
    return normalized == "拍卖"


async def unified_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    message = update.effective_message
    sender_chat = getattr(message, "sender_chat", None) if message is not None else None
    user = build_sender_chat_actor(message) if sender_chat is not None and message is not None else resolve_message_actor(update)
    message_text = (message.text or message.caption or "") if message else ""
    sender_chat_id = getattr(sender_chat, "id", None)

    log.warning(
        "=== UNIFIED_GROUP_MESSAGE_HANDLER ENTRY ===",
        chat_id=chat.id if chat else None,
        user_id=user.id if user else None,
        sender_chat_id=sender_chat_id,
        message_text=message_text[:50],
    )

    if chat is None or message is None or user is None:
        return False

    if chat.type == "private":
        return False

    sender_chat_actor = is_sender_chat_actor(user)
    real_user_id = None if sender_chat_actor or user.id <= 0 else user.id

    is_admin = False
    if real_user_id is not None:
        try:
            is_admin = await is_user_admin(context, chat.id, real_user_id)
        except Exception as exc:
            log.warning("admin_check_failed", chat_id=chat.id, user_id=real_user_id, error=str(exc))
    else:
        log.info(
            "unified_handler_skip_admin_check_sender_chat",
            chat_id=chat.id,
            sender_chat_id=sender_chat_id,
        )

    log.info(
        "unified_handler_admin_check",
        chat_id=chat.id,
        user_id=real_user_id,
        sender_chat_id=sender_chat_id,
        is_admin=is_admin,
    )

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        old_user = await session.get(TgUser, real_user_id) if real_user_id is not None else None
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
            user_id=real_user_id,
            username=user.username if real_user_id is not None else None,
            first_name=user.first_name if real_user_id is not None else None,
            last_name=user.last_name if real_user_id is not None else None,
            language_code=user.language_code if real_user_id is not None else None,
        )
        await session.commit()

    if real_user_id is not None and await _process_rename_monitor(context, chat, user, settings, old_username, old_name):
        log.info("rename_monitor_processed", chat_id=chat.id, user_id=user.id)

    if await _process_group_lock_controls(context, chat, user, message, settings, is_admin, message_text):
        return True

    if await _process_night_mode(context, chat, user, message, settings, is_admin):
        return True

    if real_user_id is not None and is_admin and await _process_alliance_reply_ban(context, db, chat, user, message, message_text):
        return True

    if real_user_id is not None and not is_admin:
        if await _process_alliance_joint_ban(context, db, chat, user, message):
            return True
        if not await _check_force_subscribe(context, chat, user, message, settings):
            return True
        if await _process_new_member_limit(context, db, chat, user, message, settings):
            return True

    if real_user_id is not None and message_text:
        if await try_bottom_button_text_trigger(update, context, chat.id, message_text):
            return True

    if real_user_id is not None and await _process_garage_features(context, db, chat, user, message, message_text, settings, is_admin):
        return True

    if message_text:
        if (real_user_id is not None and not is_admin) or sender_chat_actor:
            deleted = await _process_banned_word_check(context, db, chat, user, message, message_text, settings)
            if deleted:
                return True
        elif is_admin:
            log.info("unified_handler_skip_banned_word_admin", chat_id=chat.id, user_id=user.id)
        elif sender_chat_actor:
            log.info(
                "unified_handler_skip_user_moderation_sender_chat",
                chat_id=chat.id,
                sender_chat_id=sender_chat_id,
            )

        if not _is_reserved_activity_trigger(message_text):
            await _process_auto_reply(context, db, chat, message, message_text)

    return False
