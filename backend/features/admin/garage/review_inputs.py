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
    *, state,
    target_chat_id: int,
    message_text: str,
) -> bool:
    from backend.features.garage.services.garage_features_service import CarReviewService

    if update.effective_user is None or update.effective_message is None:
        return True

    text_value = message_text.strip()
    state_type = state.state_type
    state_data = getattr(state, "state_data", {}) or {}

    if state_type == "car_review_reward_points_input":
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("请输入正整数。")
            return True
        await CarReviewService.update_setting(session, target_chat_id, reward_points=int(text_value))
        await _finish_review_input(update, context, session, target_chat_id=target_chat_id)
        return True

    if state_type in {"car_review_submit_command_input", "car_review_rank_command_input"}:
        if not text_value:
            await update.effective_message.reply_text("指令不能为空。")
            return True
        field_name = "submit_command" if state_type == "car_review_submit_command_input" else "rank_command"
        await CarReviewService.update_setting(session, target_chat_id, **{field_name: text_value[:64]})
        await _finish_review_input(update, context, session, target_chat_id=target_chat_id)
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
        await _finish_review_input(update, context, session, target_chat_id=target_chat_id)
        return True

    if state_type == "car_review_template_input":
        if not text_value:
            await update.effective_message.reply_text("模板不能为空。")
            return True
        await CarReviewService.update_setting(session, target_chat_id, template_text=message_text)
        await _finish_review_input(update, context, session, target_chat_id=target_chat_id)
        return True

    if state_type == "car_review_field_add_input":
        parts = text_value.split(maxsplit=1)
        if len(parts) != 2:
            await update.effective_message.reply_text("请输入“字段键 字段名称”，例如：safe_score 安全感。")
            return True
        try:
            await CarReviewService.add_custom_field(
                session,
                target_chat_id,
                field_key=parts[0],
                field_label=parts[1],
            )
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
        await _finish_review_input(update, context, session, target_chat_id=target_chat_id, show_fields=True)
        return True

    if state_type == "car_review_field_label_input":
        field_id = state_data.get("field_id")
        if not isinstance(field_id, int):
            await update.effective_message.reply_text("字段状态异常，请重新进入自定义项页面。")
            return True
        try:
            item = await CarReviewService.update_custom_field_label(session, target_chat_id, field_id, field_label=text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
        if item is None:
            await update.effective_message.reply_text("字段不存在。")
            return True
        await _finish_review_input(update, context, session, target_chat_id=target_chat_id, show_fields=True)
        return True

    return False


async def _finish_review_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, target_chat_id: int,

    show_fields: bool = False,
) -> None:
    if update.effective_user is None:
        return
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    if show_fields:
        await admin_handler_instance()._show_car_review_fields_menu(update, context, target_chat_id)
    else:
        await admin_handler_instance()._show_car_review_menu(update, context, target_chat_id)
