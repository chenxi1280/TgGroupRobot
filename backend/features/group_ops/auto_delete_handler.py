from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.group_ops.services.group_daily_stats import record_group_leave_event
from backend.shared.services.module_settings_service import ModuleSettingsService

log = structlog.get_logger(__name__)


EXTRA_SYSTEM_MESSAGE_FIELDS: tuple[str, ...] = (
    "forum_topic_created",
    "forum_topic_edited",
    "forum_topic_closed",
    "forum_topic_reopened",
    "general_forum_topic_hidden",
    "general_forum_topic_unhidden",
    "users_shared",
    "chat_shared",
    "is_automatic_forward",
    "video_chat_started",
    "video_chat_scheduled",
    "video_chat_ended",
    "video_chat_participants_invited",
    "migrate_to_chat_id",
    "migrate_from_chat_id",
    "message_auto_delete_timer_changed",
    "write_access_allowed",
    "boost_added",
    "giveaway_created",
    "giveaway",
    "giveaway_winners",
    "giveaway_completed",
)


def _all_auto_delete_switches_enabled(settings) -> bool:
    return all(
        bool(getattr(settings, attr, False))
        for attr in (
            "auto_delete_join",
            "auto_delete_left",
            "auto_delete_pinned",
            "auto_delete_avatar",
            "auto_delete_title",
            "auto_delete_anonymous",
        )
    )


def _has_extra_system_message(message) -> bool:
    return any(bool(getattr(message, field, None)) for field in EXTRA_SYSTEM_MESSAGE_FIELDS)


def _is_group_anonymous_admin_message(update: Update, message) -> bool:
    from_user = getattr(message, "from_user", None)
    return (
        update.effective_chat is not None
        and update.effective_chat.type == "supergroup"
        and from_user is not None
        and from_user.id == 1087968824
    )


def should_auto_delete_message(settings, update: Update, message) -> bool:
    if bool(getattr(settings, "auto_delete_join", False)) and bool(getattr(message, "new_chat_members", None)):
        return True
    if bool(getattr(settings, "auto_delete_left", False)) and bool(getattr(message, "left_chat_member", None)):
        return True
    if bool(getattr(settings, "auto_delete_pinned", False)) and bool(getattr(message, "pinned_message", None)):
        return True
    if bool(getattr(settings, "auto_delete_title", False)) and bool(getattr(message, "new_chat_title", None)):
        return True
    if bool(getattr(settings, "auto_delete_avatar", False)) and (
        bool(getattr(message, "new_chat_photo", None)) or bool(getattr(message, "delete_chat_photo", None))
    ):
        return True
    if bool(getattr(settings, "auto_delete_anonymous", False)) and _is_group_anonymous_admin_message(update, message):
        return True

    # The UI has six common switches. If an admin enables all of them, treat
    # the remaining Telegram service-message fields as part of "all prompts".
    return _all_auto_delete_switches_enabled(settings) and _has_extra_system_message(message)


async def auto_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动删除系统消息处理器"""
    if update.effective_chat is None or update.effective_message is None:
        return

    # 只在群聊中处理
    if update.effective_chat.type not in ["group", "supergroup"]:
        return

    message = update.effective_message
    chat = update.effective_chat

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        settings = await ModuleSettingsService.ensure(
            session,
            chat_id=chat.id,
            chat_type=chat.type,
            title=chat.title,
        )

        if getattr(message, "left_chat_member", None):
            await record_group_leave_event(session, chat.id)

        # 检查是否开启自动删除
        if not settings.auto_delete_enabled:
            await session.commit()
            return

        should_delete = should_auto_delete_message(settings, update, message)

        await session.commit()

    # 删除消息
    if should_delete:
        try:
            await message.delete()
            log.debug("auto_deleted_message", chat_id=chat.id, message_id=message.message_id)
        except Exception as e:
            log.warning("auto_delete_failed", chat_id=chat.id, message_id=message.message_id, error=str(e))
