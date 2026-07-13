from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import (
    admin_handler_instance,
    clear_admin_input_state,
    require_garage_manage,
    target_chat_id_from_state,
)
from backend.shared.services.base import ValidationError


async def handle_alliance_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    from backend.features.garage.services.alliance_service import AllianceService

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = target_chat_id_from_state(state)
    if not await require_garage_manage(update, context, target_chat_id):
        return

    try:
        if state.state_type == "alliance_create_name_input":
            _, invite_code = await AllianceService.create_alliance(
                session,
                chat_id=target_chat_id,
                operator_user_id=update.effective_user.id,
                name=message_text,
            )
            notice = f"联盟创建成功，邀请码：{invite_code}"
        elif state.state_type == "alliance_join_code_input":
            alliance = await AllianceService.join_alliance(
                session,
                chat_id=target_chat_id,
                operator_user_id=update.effective_user.id,
                invite_code=message_text,
            )
            notice = f"已加入联盟：{alliance.name}"
        else:
            await update.effective_message.reply_text("联盟输入状态异常，请重新进入页面。")
            return
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(notice)
    await admin_handler_instance()._show_alliance_menu(update, context, target_chat_id)
