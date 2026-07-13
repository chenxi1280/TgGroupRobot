from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.auth_inputs import handle_auth_feature_input
from backend.features.admin.garage.input_runtime import require_garage_manage, target_chat_id_from_state
from backend.features.admin.garage.review_inputs import handle_car_review_feature_input
from backend.features.admin.garage.teacher_search_inputs import handle_teacher_search_feature_input


async def handle_garage_features_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = target_chat_id_from_state(state)
    if not await require_garage_manage(update, context, target_chat_id):
        return

    state_type = state.state_type
    text_value = message_text.strip()

    if await handle_auth_feature_input(update, context, session, state_type=state_type, target_chat_id=target_chat_id, text_value=text_value):
        return
    if await handle_teacher_search_feature_input(update, context, session, state=state, target_chat_id=target_chat_id, text_value=text_value):
        return
    if await handle_car_review_feature_input(update, context, session, state=state, target_chat_id=target_chat_id, message_text=message_text):
        return

    await update.effective_message.reply_text("配置状态异常，请重新进入页面。")
