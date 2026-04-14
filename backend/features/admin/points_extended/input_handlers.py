from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.services.permission_service import PermissionPolicyService
from backend.features.admin.points_extended.custom_inputs import handle_custom_points_input
from backend.features.admin.points_extended.level_inputs import handle_points_level_input
from backend.features.admin.points_extended.mall_inputs import handle_points_mall_input


async def handle_points_extended_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return

    if await handle_custom_points_input(
        update,
        context,
        session,
        state,
        message_text,
        target_chat_id=target_chat_id,
    ):
        return

    if await handle_points_level_input(
        update,
        context,
        session,
        state,
        message_text,
        target_chat_id=target_chat_id,
    ):
        return

    if await handle_points_mall_input(
        update,
        context,
        session,
        state,
        message_text,
        target_chat_id=target_chat_id,
    ):
        return

    await update.effective_message.reply_text("当前积分扩展配置状态不支持该输入，请重新进入配置页面。")
