from __future__ import annotations

import structlog
from dataclasses import dataclass
from typing import Any

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
from .garage import _index_garage_channel_post, _process_garage_features
from .moderation import (
    _process_alliance_joint_ban,
    _process_alliance_reply_ban,
    _process_auto_reply,
    _process_banned_word_check,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _GroupMessageRuntime:
    chat: Any
    message: Any
    user: Any
    message_text: str
    sender_chat: Any | None
    sender_chat_id: int | None
    sender_chat_actor: bool
    real_user_id: int | None


def _is_reserved_activity_trigger(message_text: str) -> bool:
    normalized = "".join(
        char
        for char in message_text
        if not char.isspace() and char not in {"\u200b", "\u200c", "\u200d", "\ufeff"}
    )
    if normalized.startswith("💰"):
        normalized = normalized[1:]
    return normalized == "拍卖"


def _resolve_actor(update: Update, message, sender_chat):
    if sender_chat is not None and message is not None:
        return build_sender_chat_actor(message)
    return resolve_message_actor(update)


def _old_user_identity(old_user) -> tuple[str | None, str]:
    if old_user is None:
        return None, ""
    parts = [part for part in (old_user.first_name, old_user.last_name) if part]
    return old_user.username, " ".join(parts)


def _runtime_user_profile(runtime: _GroupMessageRuntime) -> dict[str, object | None]:
    if runtime.real_user_id is None:
        return {"username": None, "first_name": None, "last_name": None, "language_code": None}
    return {
        "username": runtime.user.username,
        "first_name": runtime.user.first_name,
        "last_name": runtime.user.last_name,
        "language_code": runtime.user.language_code,
    }


def _runtime_inputs(update: Update):
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None or chat.type == "private":
        return None
    sender_chat = getattr(message, "sender_chat", None)
    user = _resolve_actor(update, message, sender_chat)
    if user is None:
        return None
    message_text = message.text or message.caption or ""
    return chat, message, sender_chat, user, message_text


def _resolve_runtime(update: Update) -> _GroupMessageRuntime | None:
    inputs = _runtime_inputs(update)
    if inputs is None:
        return None
    chat, message, sender_chat, user, message_text = inputs
    sender_chat_id = getattr(sender_chat, "id", None)
    log.warning(
        "=== UNIFIED_GROUP_MESSAGE_HANDLER ENTRY ===",
        chat_id=chat.id,
        user_id=user.id,
        sender_chat_id=sender_chat_id,
        message_text=message_text[:50],
    )
    sender_chat_actor = is_sender_chat_actor(user)
    real_user_id = None if sender_chat_actor or user.id <= 0 else user.id
    return _GroupMessageRuntime(
        chat=chat,
        message=message,
        user=user,
        message_text=message_text,
        sender_chat=sender_chat,
        sender_chat_id=sender_chat_id,
        sender_chat_actor=sender_chat_actor,
        real_user_id=real_user_id,
    )


async def _resolve_admin_status(context: ContextTypes.DEFAULT_TYPE, runtime: _GroupMessageRuntime) -> bool:
    if runtime.real_user_id is None:
        log.info(
            "unified_handler_skip_admin_check_sender_chat",
            chat_id=runtime.chat.id,
            sender_chat_id=runtime.sender_chat_id,
        )
        return False
    try:
        return await is_user_admin(context, runtime.chat.id, runtime.real_user_id)
    except Exception as exc:
        log.warning(
            "admin_check_failed",
            chat_id=runtime.chat.id,
            user_id=runtime.real_user_id,
            error=str(exc),
        )
        return False


async def _load_chat_settings(context: ContextTypes.DEFAULT_TYPE, runtime: _GroupMessageRuntime):
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        old_user = await session.get(TgUser, runtime.real_user_id) if runtime.real_user_id is not None else None
        old_username, old_name = _old_user_identity(old_user)
        profile = _runtime_user_profile(runtime)
        settings = await ModuleSettingsService.ensure(
            session,
            runtime.chat.id,
            chat_type=runtime.chat.type,
            title=runtime.chat.title,
            user_id=runtime.real_user_id,
            **profile,
        )
        await session.commit()
    return db, settings, old_username, old_name


async def _process_control_hooks(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    runtime: _GroupMessageRuntime,
    db: Database,
    settings,
    is_admin: bool,
) -> bool:
    if await _process_group_lock_controls(
        context,
        runtime.chat,
        runtime.user,
        message=runtime.message,
        settings=settings,
        is_admin=is_admin,
        message_text=runtime.message_text,
    ):
        return True
    if await _process_night_mode(context, runtime.chat, runtime.user, runtime.message, settings, is_admin):
        return True
    if runtime.real_user_id is not None and is_admin:
        return await _process_alliance_reply_ban(
            context,
            db,
            runtime.chat,
            user=runtime.user,
            message=runtime.message,
            message_text=runtime.message_text,
        )
    if runtime.real_user_id is None or is_admin:
        return False
    if await _process_alliance_joint_ban(context, db, runtime.chat, user=runtime.user, message=runtime.message):
        return True
    if not await _check_force_subscribe(context, runtime.chat, runtime.user, message=runtime.message, settings=settings):
        return True
    return await _process_new_member_limit(context, db, runtime.chat, runtime.user, runtime.message, settings)


async def _process_feature_hooks(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    update: Update,
    runtime: _GroupMessageRuntime,
    db: Database,
    settings,
    is_admin: bool,
) -> bool:
    if runtime.real_user_id is not None and runtime.message_text:
        if await try_bottom_button_text_trigger(update, context, runtime.chat.id, button_text=runtime.message_text):
            return True
    if runtime.sender_chat_actor and runtime.message_text:
        await _index_garage_channel_post(context, db, runtime.chat, message=runtime.message, message_text=runtime.message_text)
    if runtime.real_user_id is not None:
        if await _process_garage_features(
            context,
            db,
            runtime.chat,
            user=runtime.user,
            message=runtime.message,
            message_text=runtime.message_text,
            settings=settings,
            is_admin=is_admin,
        ):
            return True
    return await _process_moderation_and_auto_reply(
        context,
        runtime=runtime,
        db=db,
        settings=settings,
        is_admin=is_admin,
    )


async def _process_moderation_and_auto_reply(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    runtime: _GroupMessageRuntime,
    db: Database,
    settings,
    is_admin: bool,
) -> bool:
    if not runtime.message_text:
        return False
    if (runtime.real_user_id is not None and not is_admin) or runtime.sender_chat_actor:
        deleted = await _process_banned_word_check(
            context,
            db,
            runtime.chat,
            user=runtime.user,
            message=runtime.message,
            message_text=runtime.message_text,
            settings=settings,
        )
        if deleted:
            return True
    elif is_admin:
        log.info(
            "unified_handler_skip_banned_word_admin",
            chat_id=runtime.chat.id,
            user_id=runtime.user.id,
        )
    elif runtime.sender_chat_actor:
        log.info(
            "unified_handler_skip_user_moderation_sender_chat",
            chat_id=runtime.chat.id,
            sender_chat_id=runtime.sender_chat_id,
        )
    if not _is_reserved_activity_trigger(runtime.message_text):
        await _process_auto_reply(context, db, runtime.chat, message=runtime.message, message_text=runtime.message_text)
    return False


async def unified_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    runtime = _resolve_runtime(update)
    if runtime is None:
        return False

    is_admin = await _resolve_admin_status(context, runtime)

    log.info(
        "unified_handler_admin_check",
        chat_id=runtime.chat.id,
        user_id=runtime.real_user_id,
        sender_chat_id=runtime.sender_chat_id,
        is_admin=is_admin,
    )

    db, settings, old_username, old_name = await _load_chat_settings(context, runtime)

    if runtime.real_user_id is not None and await _process_rename_monitor(
        context,
        runtime.chat,
        runtime.user,
        settings=settings,
        old_username=old_username,
        old_name=old_name,
    ):
        log.info("rename_monitor_processed", chat_id=runtime.chat.id, user_id=runtime.user.id)

    if await _process_control_hooks(context, runtime=runtime, db=db, settings=settings, is_admin=is_admin):
        return True

    if await _process_feature_hooks(
        context,
        update=update,
        runtime=runtime,
        db=db,
        settings=settings,
        is_admin=is_admin,
    ):
        return True

    return False
