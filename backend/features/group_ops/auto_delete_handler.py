from __future__ import annotations

import time

import structlog
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.group_ops.services.group_daily_stats import record_group_leave_event
from backend.shared.services.module_settings_service import ModuleSettingsService

log = structlog.get_logger(__name__)

AUTO_DELETE_FAILURE_ALERT_TTL_SECONDS = 600
AUTO_DELETE_FAILURE_ALERT_CACHE_KEY = "_auto_delete_failure_alerts"


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


def _chat_member_status_value(member) -> str:
    status = getattr(member, "status", "") or ""
    return str(getattr(status, "value", status)).lower()


def _has_delete_permission(member) -> bool:
    status = _chat_member_status_value(member)
    if status == "creator":
        return True
    return status == "administrator" and bool(getattr(member, "can_delete_messages", False))


async def get_auto_delete_permission_warning(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> str | None:
    try:
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(chat_id, me.id)
    except Exception as exc:
        log.warning("auto_delete_permission_check_failed", chat_id=chat_id, error=str(exc))
        return "⚠️ 权限提醒：暂时无法确认 Bot 删除消息权限，请确认 Bot 已在本群并具备「删除消息」权限。"

    if _has_delete_permission(member):
        return None

    status = _chat_member_status_value(member)
    if status != "administrator":
        return "⚠️ 权限提醒：Bot 目前不是本群管理员，删除系统提示不会生效。请先把 Bot 设为管理员，并打开「删除消息」权限。"
    return "⚠️ 权限提醒：Bot 当前缺少「删除消息」权限，删除系统提示不会生效。请在群管理权限里打开该权限。"


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


def _any_auto_delete_switch_enabled(settings) -> bool:
    return any(
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


def _describe_system_message(message) -> str:
    if bool(getattr(message, "new_chat_members", None)):
        return "进群消息"
    if bool(getattr(message, "left_chat_member", None)):
        return "退群消息"
    if bool(getattr(message, "pinned_message", None)):
        return "置顶通知"
    if bool(getattr(message, "new_chat_title", None)):
        return "修改群名"
    if bool(getattr(message, "new_chat_photo", None)) or bool(getattr(message, "delete_chat_photo", None)):
        return "修改群头像"
    if bool(getattr(message, "forum_topic_created", None)) or bool(getattr(message, "forum_topic_edited", None)):
        return "话题提示"
    return "系统提示"


def _should_send_failure_alert(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_type: str) -> bool:
    cache = context.application.bot_data.setdefault(AUTO_DELETE_FAILURE_ALERT_CACHE_KEY, {})
    key = (chat_id, message_type)
    now = time.monotonic()
    last_sent_at = float(cache.get(key, 0) or 0)
    if now - last_sent_at < AUTO_DELETE_FAILURE_ALERT_TTL_SECONDS:
        return False
    cache[key] = now
    return True


async def _notify_auto_delete_failure(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error: Exception,
) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    from_user = getattr(message, "from_user", None) or update.effective_user
    if from_user is None or bool(getattr(from_user, "is_bot", False)):
        return

    message_type = _describe_system_message(message)
    if not _should_send_failure_alert(context, chat.id, message_type):
        return

    chat_title = getattr(chat, "title", None) or f"群组 {chat.id}"
    text = (
        "⚠️ 删除系统提示未生效\n\n"
        f"群组：{chat_title}\n"
        f"提示类型：{message_type}\n"
        f"失败原因：{error}\n\n"
        "请把 Bot 设为群管理员，并打开「删除消息」权限；权限生效后，新产生的系统提示才会自动删除。"
    )
    try:
        await context.bot.send_message(chat_id=from_user.id, text=text)
    except TelegramError as exc:
        log.warning(
            "auto_delete_failure_alert_failed",
            chat_id=chat.id,
            user_id=getattr(from_user, "id", None),
            error=str(exc),
        )


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

        # 兼容旧数据：菜单按分项开关展示生效状态，运行时也应以分项开关兜底。
        if not (bool(getattr(settings, "auto_delete_enabled", False)) or _any_auto_delete_switch_enabled(settings)):
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
            await _notify_auto_delete_failure(update, context, e)
