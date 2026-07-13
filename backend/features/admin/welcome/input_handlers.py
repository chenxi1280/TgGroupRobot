from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

def _admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


def _admin_module():
    import backend.features.admin.admin_handler as admin_handler_module

    return admin_handler_module


async def _apply_welcome_cover(
    update, session, *, service, target_chat_id: int, welcome_id: int,
    message_text: str,
) -> bool:
    if message_text.strip() == "清空":
        await service.update_field(
            session, target_chat_id, welcome_id,
            cover_media_type=None, cover_media_file_id=None,
        )
        return True
    message = update.effective_message
    media = None
    if message.photo:
        media = ("photo", message.photo[-1].file_id)
    elif message.video:
        media = ("video", message.video.file_id)
    if media is None:
        await message.reply_text("请发送图片或视频，或发送“清空”移除封面。")
        return False
    await service.update_field(
        session, target_chat_id, welcome_id,
        cover_media_type=media[0], cover_media_file_id=media[1],
    )
    return True


async def _apply_welcome_input(
    update, session, *, service, state_type: str, target_chat_id: int,
    welcome_id: int, message_text: str,
) -> bool:
    field_names = {
        "welcome_title_input": "title",
        "welcome_text_input": "text_content",
    }
    field = field_names.get(state_type)
    if field is not None:
        await service.update_field(
            session, target_chat_id, welcome_id, **{field: message_text}
        )
        return True
    if state_type == "welcome_cover_input":
        return await _apply_welcome_cover(
            update, session, service=service, target_chat_id=target_chat_id,
            welcome_id=welcome_id, message_text=message_text,
        )
    await update.effective_message.reply_text("未识别的欢迎消息输入状态，请重新进入配置页。")
    return False


async def _finish_welcome_input(
    update, context, session, *, target_chat_id: int, welcome_id: int,
    clear_user_state, clear_private_input_state,
) -> None:
    user_id = update.effective_user.id
    await clear_user_state(session, chat_id=target_chat_id, user_id=user_id)
    if target_chat_id != user_id:
        await clear_private_input_state(session, user_id)
    await session.commit()
    await _admin_handler_instance()._show_welcome_detail_menu(
        update, context, target_chat_id, welcome_id=welcome_id
    )


async def handle_welcome_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_private_input_state, clear_user_state
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

    applied = await _apply_welcome_input(
        update, session, service=WelcomeService, state_type=state.state_type,
        target_chat_id=target_chat_id, welcome_id=welcome_id,
        message_text=message_text,
    )
    if not applied:
        return
    await _finish_welcome_input(
        update, context, session, target_chat_id=target_chat_id,
        welcome_id=welcome_id, clear_user_state=clear_user_state,
        clear_private_input_state=clear_private_input_state,
    )
