from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.module_settings.input_runtime import (
    admin_handler_instance,
    admin_module,
    clear_admin_input_state,
    require_settings_manage,
    target_chat_id_from_state,
)
from backend.features.admin.module_settings.input_utils import is_valid_hhmm
from backend.shared.services.command_config_service import set_command_alias


async def handle_new_member_limit_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = target_chat_id_from_state(state)
    field = state.state_data.get("field")
    if not await require_settings_manage(update, context, target_chat_id):
        return
    settings = await admin_module().get_chat_settings(session, target_chat_id)

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

    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_new_member_limit_menu(update, context, target_chat_id)


async def _apply_night_time(message, settings, *, field: str, text_value: str) -> bool:
    if not is_valid_hhmm(text_value):
        example = "22:00" if field == "start" else "07:00"
        await message.reply_text(f"时间格式错误，请使用 HH:MM，例如 {example}")
        return False
    if field == "start":
        settings.night_mode_start_time = text_value
        settings.group_lock_close_time = text_value
    else:
        settings.night_mode_end_time = text_value
        settings.group_lock_open_time = text_value
    return True


async def _apply_night_whitelist(message, settings, text_value: str) -> bool:
    if text_value in {"清空", "clear"}:
        settings.night_mode_whitelist_user_ids = []
        return True
    parts = [item for item in re.split(r"[\s,，]+", text_value) if item]
    if not parts:
        await message.reply_text("未识别到有效的用户ID。")
        return False
    if any(not re.fullmatch(r"\d+", item) for item in parts):
        await message.reply_text("用户ID仅支持数字格式，请重新输入。")
        return False
    settings.night_mode_whitelist_user_ids = [int(item) for item in parts]
    return True


async def _apply_night_mode_value(message, settings, *, field: str, text_value: str) -> bool:
    if field in {"start", "end"}:
        return await _apply_night_time(message, settings, field=field, text_value=text_value)
    if field == "whitelist":
        return await _apply_night_whitelist(message, settings, text_value)
    attributes = {
        "warn_text": ("night_mode_warn_text", "提示文案不能为空。"),
        "open_phrase": ("group_lock_open_phrase", "开群词不能为空。"),
        "close_phrase": ("group_lock_close_phrase", "关群词不能为空。"),
    }
    target = attributes.get(field)
    if target is None:
        await message.reply_text("夜间管控配置状态已失效，请重新进入。")
        return False
    if not text_value:
        await message.reply_text(target[1])
        return False
    setattr(settings, target[0], text_value)
    return True


async def handle_night_mode_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = target_chat_id_from_state(state)
    field = state.state_data.get("field")
    if not await require_settings_manage(update, context, target_chat_id):
        return
    settings = await admin_module().get_chat_settings(session, target_chat_id)

    applied = await _apply_night_mode_value(
        update.effective_message,
        settings,
        field=field,
        text_value=message_text.strip(),
    )
    if not applied:
        return

    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_night_mode_menu(update, context, target_chat_id)


async def handle_command_config_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = target_chat_id_from_state(state)
    command_key = state.state_data.get("command_key")
    if not command_key:
        await update.effective_message.reply_text("命令配置状态已失效，请重新进入。")
        return
    if not await require_settings_manage(update, context, target_chat_id):
        return
    settings = await admin_module().get_chat_settings(session, target_chat_id)

    text_value = message_text.strip()
    alias = None if text_value in {"", "清空"} else text_value
    set_command_alias(settings, command_key, alias)

    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_command_config_detail(update, context, target_chat_id, command_key=command_key)
