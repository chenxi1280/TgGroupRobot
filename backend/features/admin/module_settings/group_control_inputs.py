from __future__ import annotations

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


async def handle_group_lock_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = target_chat_id_from_state(state)
    if not await require_settings_manage(update, context, target_chat_id):
        return
    settings = await admin_module().get_chat_settings(session, target_chat_id)
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
        settings.night_mode_end_time = value
    elif state.state_type == "group_lock_close_time_input":
        value = message_text.strip()
        if not is_valid_hhmm(value):
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM，例如 02:00")
            return
        settings.group_lock_close_time = value
        settings.night_mode_start_time = value
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_night_mode_menu(update, context, target_chat_id)


async def handle_rename_monitor_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None:
        return
    target_chat_id = target_chat_id_from_state(state)
    if not await require_settings_manage(update, context, target_chat_id):
        return
    settings = await admin_module().get_chat_settings(session, target_chat_id)
    settings.name_change_monitor_template_text = message_text.strip()
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_rename_monitor_menu(update, context, target_chat_id)
