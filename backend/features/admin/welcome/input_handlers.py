from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.services.permission_service import PermissionPolicyService


def _admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


def _admin_module():
    import backend.features.admin.admin_handler as admin_handler_module

    return admin_handler_module


async def handle_welcome_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state
    from backend.features.verification.welcome_service import WelcomeService

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    welcome_id = state.state_data.get("welcome_id")
    if not isinstance(welcome_id, int):
        await update.effective_message.reply_text("欢迎配置上下文已失效，请重新进入配置页。")
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

    if state.state_type == "welcome_title_input":
        await WelcomeService.update_field(session, target_chat_id, welcome_id, title=message_text)
    elif state.state_type == "welcome_text_input":
        await WelcomeService.update_field(session, target_chat_id, welcome_id, text_content=message_text)
    elif state.state_type == "welcome_cover_input":
        if message_text.strip() == "清空":
            await WelcomeService.update_field(
                session,
                target_chat_id,
                welcome_id,
                cover_media_type=None,
                cover_media_file_id=None,
            )
        else:
            message = update.effective_message
            if message.photo:
                await WelcomeService.update_field(
                    session,
                    target_chat_id,
                    welcome_id,
                    cover_media_type="photo",
                    cover_media_file_id=message.photo[-1].file_id,
                )
            elif message.video:
                await WelcomeService.update_field(
                    session,
                    target_chat_id,
                    welcome_id,
                    cover_media_type="video",
                    cover_media_file_id=message.video.file_id,
                )
            else:
                await update.effective_message.reply_text("请发送图片或视频，或发送“清空”移除封面。")
                return

    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler_instance()._show_welcome_detail_menu(update, context, target_chat_id, welcome_id)
