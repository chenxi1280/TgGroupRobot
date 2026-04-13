from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import admin_handler_instance, clear_admin_input_state
from backend.shared.services.base import ValidationError


async def handle_auth_feature_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state_type: str,
    target_chat_id: int,
    text_value: str,
) -> bool:
    from backend.features.garage.services.garage_features_service import GarageAuthService

    if update.effective_user is None or update.effective_message is None:
        return True

    if state_type == "garage_badge_input":
        if not text_value:
            await update.effective_message.reply_text("认证图标不能为空。")
            return True
        await GarageAuthService.update_settings(session, target_chat_id, garage_auth_badge=text_value[:16])
        await _finish_auth_input(update, context, session, target_chat_id)
        return True

    if state_type == "garage_teacher_input":
        try:
            await GarageAuthService.add_teacher(session, target_chat_id, update.effective_user.id, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
        await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()
        await admin_handler_instance()._show_garage_teacher_list_menu(update, context, target_chat_id, 0)
        return True

    if state_type == "garage_whitelist_input":
        try:
            await GarageAuthService.add_whitelist(session, target_chat_id, update.effective_user.id, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
        await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()
        await admin_handler_instance()._show_garage_whitelist_menu(update, context, target_chat_id, 0)
        return True

    if state_type in {"garage_limit_interval_input", "garage_limit_max_count_input"}:
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("请输入正整数。")
            return True
        number = int(text_value)
        update_kwargs = (
            {"garage_limit_interval_sec": number}
            if state_type == "garage_limit_interval_input"
            else {"garage_limit_max_count": number}
        )
        await GarageAuthService.update_settings(session, target_chat_id, **update_kwargs)
        await _finish_auth_input(update, context, session, target_chat_id)
        return True

    return False


async def _finish_auth_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
) -> None:
    if update.effective_user is None:
        return
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_garage_auth_menu(update, context, target_chat_id)
