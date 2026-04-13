from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


def admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


def admin_module():
    import backend.features.admin.admin_handler as admin_handler_module

    return admin_handler_module


def target_chat_id_from_state(state) -> int:
    return state.state_data.get("target_chat_id", state.chat_id)


async def require_garage_manage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return False

    allowed, error_text = await admin_module().PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed and error_text:
        await update.effective_message.reply_text(error_text)
    return allowed


async def clear_admin_input_state(session, *, target_chat_id: int, user_id: int) -> None:
    from backend.platform.state.state_service import clear_user_state

    await clear_user_state(session, chat_id=target_chat_id, user_id=user_id)
    await clear_user_state(session, chat_id=user_id, user_id=user_id)
