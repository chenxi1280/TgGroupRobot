from __future__ import annotations

import json
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.shared.services.base import ValidationError
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.command_config_service import set_command_alias
from backend.shared.services.permission_service import PermissionPolicyService


def _admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


def _admin_module():
    import backend.features.admin.admin_handler as admin_handler_module

    return admin_handler_module


def is_valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", (value or "").strip()))


def format_duration_label(seconds: int) -> str:
    safe_seconds = max(int(seconds or 0), 0)
    minutes = (safe_seconds + 59) // 60
    hours, rem = divmod(minutes, 60)
    if hours:
        if rem:
            return f"{hours}小时{rem}分钟"
        return f"{hours}小时"
    return f"{minutes}分钟"


def parse_force_subscribe_buttons_input(raw_text: str) -> list[list[dict]]:
    text = (raw_text or "").strip()
    if not text:
        raise ValidationError("按钮配置不能为空。")
    if text.startswith("["):
        return json.loads(text)

    rows: list[list[dict]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" not in line:
            raise ValidationError("文本格式错误：每行必须包含“按钮文案|URL”。")
        button_text, button_url = [part.strip() for part in line.split("|", 1)]
        if not button_text or not button_url:
            raise ValidationError("按钮文案和 URL 不能为空。")
        rows.append([{"text": button_text[:32], "url": button_url}])
    if not rows:
        raise ValidationError("未解析到有效按钮。")
    return rows


def _build_force_subscribe_channel_button_preview(value: str | None) -> InlineKeyboardButton | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.startswith("@"):
        return InlineKeyboardButton(normalized, url=f"https://t.me/{normalized[1:]}")
    if normalized.startswith("https://t.me/") or normalized.startswith("http://t.me/"):
        return InlineKeyboardButton(normalized, url=normalized)
    return None


def build_force_subscribe_preview_markup(settings, chat_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    custom_enabled = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
    custom_buttons = getattr(settings, "force_subscribe_buttons", None) or []
    if custom_enabled and custom_buttons:
        try:
            normalized = ScheduledMessageService.normalize_buttons_config(custom_buttons)
            for row in normalized:
                rows.append([InlineKeyboardButton(item["text"], url=item["url"]) for item in row])
        except Exception:
            rows = []
    if not rows:
        fallback_buttons = [
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_1", None)),
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_2", None)),
        ]
        rows.extend([[button] for button in fallback_buttons if button is not None])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:forcesub:{chat_id}")])
    return InlineKeyboardMarkup(rows)


async def handle_force_subscribe_channel_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    admin_module = _admin_module()
    allowed, error_text = await admin_module.PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if update.effective_message is not None and error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await admin_module.get_chat_settings(session, target_chat_id)

    if state.state_type == "force_subscribe_channel_1_input":
        field = "force_subscribe_bound_channel_1"
        value = message_text.strip()
        setattr(settings, field, None if value in {"", "清空"} else value)
    elif state.state_type == "force_subscribe_channel_2_input":
        field = "force_subscribe_bound_channel_2"
        value = message_text.strip()
        setattr(settings, field, None if value in {"", "清空"} else value)
    elif state.state_type == "force_subscribe_text_input":
        field = "force_subscribe_guide_text"
        value = message_text.strip()
        if not value:
            await update.effective_message.reply_text("文案不能为空。")
            return
        setattr(settings, field, value)
    elif state.state_type == "force_subscribe_buttons_input":
        if message_text.strip() == "清空":
            settings.force_subscribe_buttons = []
            settings.force_subscribe_custom_buttons_enabled = False
        else:
            try:
                buttons = parse_force_subscribe_buttons_input(message_text)
                settings.force_subscribe_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
                settings.force_subscribe_custom_buttons_enabled = True
            except (json.JSONDecodeError, ValidationError) as exc:
                await update.effective_message.reply_text(f"按钮格式错误：{exc}")
                return
    elif state.state_type == "force_subscribe_cover_input":
        if message_text.strip() == "清空":
            settings.force_subscribe_cover_media_type = None
            settings.force_subscribe_cover_file_id = None
        else:
            message = update.effective_message
            if message.photo:
                settings.force_subscribe_cover_media_type = "photo"
                settings.force_subscribe_cover_file_id = message.photo[-1].file_id
            elif message.video:
                settings.force_subscribe_cover_media_type = "video"
                settings.force_subscribe_cover_file_id = message.video.file_id
            else:
                await update.effective_message.reply_text("请发送图片或视频，或发送“清空”移除封面。")
                return
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler_instance()._show_force_subscribe_menu(update, context, target_chat_id)


async def handle_new_member_limit_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    field = state.state_data.get("field")
    admin_module = _admin_module()
    allowed, error_text = await admin_module.PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await admin_module.get_chat_settings(session, target_chat_id)

    if field == "window":
        text_value = message_text.strip()
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("请输入正整数分钟数。")
            return
        minutes = int(text_value)
        if minutes <= 0:
            await update.effective_message.reply_text("限制时长必须大于 0。")
            return
        settings.new_member_limit_window_seconds = minutes * 60
    elif field == "warn_text":
        text_value = message_text.strip()
        if not text_value:
            await update.effective_message.reply_text("提示文案不能为空。")
            return
        settings.new_member_limit_warn_text = text_value
    else:
        await update.effective_message.reply_text("新成员限制配置状态已失效，请重新进入。")
        return

    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler_instance()._show_new_member_limit_menu(update, context, target_chat_id)


async def handle_night_mode_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    field = state.state_data.get("field")
    admin_module = _admin_module()
    allowed, error_text = await admin_module.PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await admin_module.get_chat_settings(session, target_chat_id)

    text_value = message_text.strip()
    if field == "start":
        if not is_valid_hhmm(text_value):
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM，例如 22:00")
            return
        settings.night_mode_start_time = text_value
    elif field == "end":
        if not is_valid_hhmm(text_value):
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM，例如 07:00")
            return
        settings.night_mode_end_time = text_value
    elif field == "warn_text":
        if not text_value:
            await update.effective_message.reply_text("提示文案不能为空。")
            return
        settings.night_mode_warn_text = text_value
    elif field == "whitelist":
        if text_value in {"清空", "clear"}:
            settings.night_mode_whitelist_user_ids = []
        else:
            raw_parts = [item for item in re.split(r"[\s,，]+", text_value) if item]
            if not raw_parts:
                await update.effective_message.reply_text("未识别到有效的用户ID。")
                return
            ids: list[int] = []
            for item in raw_parts:
                if not re.fullmatch(r"\d+", item):
                    await update.effective_message.reply_text("用户ID仅支持数字格式，请重新输入。")
                    return
                ids.append(int(item))
            settings.night_mode_whitelist_user_ids = ids
    else:
        await update.effective_message.reply_text("夜间模式配置状态已失效，请重新进入。")
        return

    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler_instance()._show_night_mode_menu(update, context, target_chat_id)


async def handle_command_config_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    command_key = state.state_data.get("command_key")
    if not command_key:
        await update.effective_message.reply_text("命令配置状态已失效，请重新进入。")
        return
    admin_module = _admin_module()
    allowed, error_text = await admin_module.PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await admin_module.get_chat_settings(session, target_chat_id)

    text_value = message_text.strip()
    alias = None if text_value in {"", "清空"} else text_value
    set_command_alias(settings, command_key, alias)

    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler_instance()._show_command_config_detail(update, context, target_chat_id, command_key)


async def handle_group_lock_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    admin_module = _admin_module()
    allowed, error_text = await admin_module.PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await admin_module.get_chat_settings(session, target_chat_id)
    if state.state_type == "group_lock_open_keyword_input":
        settings.group_lock_open_phrase = message_text.strip()
    elif state.state_type == "group_lock_close_keyword_input":
        settings.group_lock_close_phrase = message_text.strip()
    elif state.state_type == "group_lock_open_time_input":
        value = message_text.strip()
        if not is_valid_hhmm(value):
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM，例如 08:00")
            return
        settings.group_lock_open_time = value
    elif state.state_type == "group_lock_close_time_input":
        value = message_text.strip()
        if not is_valid_hhmm(value):
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM，例如 02:00")
            return
        settings.group_lock_close_time = value
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler_instance()._show_group_lock_menu(update, context, target_chat_id)


async def handle_rename_monitor_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    admin_module = _admin_module()
    allowed, error_text = await admin_module.PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if update.effective_message is not None and error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await admin_module.get_chat_settings(session, target_chat_id)
    settings.name_change_monitor_template_text = message_text.strip()
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler_instance()._show_rename_monitor_menu(update, context, target_chat_id)
