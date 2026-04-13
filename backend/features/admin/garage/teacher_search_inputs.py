from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import (
    admin_handler_instance,
    clear_admin_input_state,
)
from backend.shared.services.base import ValidationError


async def handle_teacher_search_feature_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    target_chat_id: int,
    text_value: str,
) -> bool:
    if state.state_type == "teacher_search_delegate_target_input":
        await _handle_delegate_target_input(update, session, target_chat_id, text_value)
        return True

    if state.state_type == "teacher_search_delegate_location_input":
        await _handle_delegate_location_input(update, context, session, state, target_chat_id, text_value)
        return True

    return False


async def _handle_delegate_target_input(
    update: Update,
    session,
    target_chat_id: int,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService
    from backend.platform.state.state_service import set_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    try:
        user = await TeacherSearchService.resolve_delegate_user(session, text_value)
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await set_user_state(
        session,
        chat_id=target_chat_id,
        user_id=update.effective_user.id,
        state_type="teacher_search_delegate_location_input",
        state_data={"target_chat_id": target_chat_id, "delegate_user_id": user.id},
    )
    await session.commit()
    await update.effective_message.reply_text("👉 请输入经纬度，格式：纬度,经度")


async def _handle_delegate_location_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    target_chat_id: int,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService

    if update.effective_user is None or update.effective_message is None:
        return

    parts = [item for item in re.split(r"[\s,，]+", text_value) if item]
    if len(parts) != 2:
        await update.effective_message.reply_text("格式错误，请输入：纬度,经度")
        return
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError:
        await update.effective_message.reply_text("经纬度格式错误，请重新输入。")
        return

    delegate_user_id = state.state_data.get("delegate_user_id")
    if not isinstance(delegate_user_id, int):
        await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("代录状态异常，请重新进入。")
        return

    await TeacherSearchService.upsert_member_location(
        session,
        chat_id=target_chat_id,
        user_id=delegate_user_id,
        latitude=latitude,
        longitude=longitude,
        operator_user_id=update.effective_user.id,
    )
    await TeacherSearchService.upsert_teacher_profile_from_location(
        session,
        chat_id=target_chat_id,
        user_id=delegate_user_id,
        latitude=latitude,
        longitude=longitude,
    )
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_teacher_search_menu(update, context, target_chat_id)
