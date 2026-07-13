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


DEFAULT_AGREEMENT_TEXT = "请阅读并同意本群规则后再发言。"
DEFAULT_MATH_PROMPT_TEXT = "请回答下面的简单算术题完成验证。"


async def _apply_verification_input(update, settings, *, state_type: str, message_text: str) -> bool:
    if state_type == "verification_cover_input":
        return await _apply_verification_cover(update, settings, message_text)
    if state_type == "vfy_agreement_text_input":
        value = message_text.strip()
        next_value = DEFAULT_AGREEMENT_TEXT if value == "清空" else value
        if not next_value:
            await update.effective_message.reply_text("条约文案不能为空。")
            return False
        settings.verification_agreement_text = next_value
        return True
    if state_type == "vfy_math_prompt_text_input":
        value = message_text.strip()
        next_value = DEFAULT_MATH_PROMPT_TEXT if value == "清空" else value
        if not next_value:
            await update.effective_message.reply_text("数学题文案不能为空。")
            return False
        settings.verification_math_prompt_text = next_value
        return True
    await update.effective_message.reply_text("进群验证配置状态已失效，请重新进入。")
    return False


async def _finish_verification_input(
    update, context, session, *, state, target_chat_id: int
) -> None:
    await clear_admin_input_state(
        session, target_chat_id=target_chat_id, user_id=update.effective_user.id
    )
    await session.commit()
    data = state.state_data if isinstance(state.state_data, dict) else {}
    return_rule = data.get("return_rule")
    if return_rule in {"button", "math", "mute"}:
        await admin_handler_instance()._show_verification_rule_detail(
            update, context, target_chat_id, mode=return_rule
        )
        return
    await admin_handler_instance()._show_verification_rules_menu(
        update, context, target_chat_id
    )


async def handle_verification_input(
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
    if not await _apply_verification_input(
        update, settings, state_type=state.state_type, message_text=message_text
    ):
        return
    await _finish_verification_input(
        update, context, session, state=state, target_chat_id=target_chat_id
    )


async def _apply_verification_cover(update: Update, settings, message_text: str) -> bool:
    message = update.effective_message
    if message is None:
        return False
    if message_text.strip() == "清空":
        settings.verification_cover_media_type = None
        settings.verification_cover_file_id = None
        return True
    if getattr(message, "photo", None):
        settings.verification_cover_media_type = "photo"
        settings.verification_cover_file_id = message.photo[-1].file_id
        return True
    if getattr(message, "video", None):
        settings.verification_cover_media_type = "video"
        settings.verification_cover_file_id = message.video.file_id
        return True
    await message.reply_text("请发送图片或视频；发送“清空”可移除封面。")
    return False
