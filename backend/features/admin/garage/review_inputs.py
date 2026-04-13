from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import admin_handler_instance, clear_admin_input_state
from backend.shared.services.base import ValidationError


async def handle_car_review_feature_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state_type: str,
    target_chat_id: int,
    message_text: str,
) -> bool:
    from backend.features.garage.services.garage_features_service import CarReviewService

    if update.effective_user is None or update.effective_message is None:
        return True

    text_value = message_text.strip()

    if state_type == "car_review_reward_points_input":
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("请输入正整数。")
            return True
        await CarReviewService.update_setting(session, target_chat_id, reward_points=int(text_value))
        await _finish_review_input(update, context, session, target_chat_id)
        return True

    if state_type in {"car_review_submit_command_input", "car_review_rank_command_input"}:
        if not text_value:
            await update.effective_message.reply_text("指令不能为空。")
            return True
        field_name = "submit_command" if state_type == "car_review_submit_command_input" else "rank_command"
        await CarReviewService.update_setting(session, target_chat_id, **{field_name: text_value[:64]})
        await _finish_review_input(update, context, session, target_chat_id)
        return True

    if state_type == "car_review_approver_input":
        approver_id = None
        if text_value != "清空":
            try:
                user = await CarReviewService.resolve_approver(session, text_value)
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return True
            approver_id = user.id
        await CarReviewService.update_setting(session, target_chat_id, approver_user_id=approver_id)
        await _finish_review_input(update, context, session, target_chat_id)
        return True

    if state_type == "car_review_template_input":
        if not text_value:
            await update.effective_message.reply_text("模板不能为空。")
            return True
        await CarReviewService.update_setting(session, target_chat_id, template_text=message_text)
        await _finish_review_input(update, context, session, target_chat_id)
        return True

    return False


async def _finish_review_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
) -> None:
    if update.effective_user is None:
        return
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_car_review_menu(update, context, target_chat_id)
