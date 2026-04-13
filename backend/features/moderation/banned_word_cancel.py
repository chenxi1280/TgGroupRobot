from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state

log = structlog.get_logger(__name__)


async def banned_word_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消违禁词配置，返回违禁词菜单"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        await q.edit_message_text("❌ 无法获取群组信息")
        return

    try:
        target_chat_id = int(parts[2])
    except ValueError:
        await q.edit_message_text("❌ 群组ID格式错误")
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_chat_id = chat.id
        await clear_user_state(session, state_chat_id, user.id)
        await session.commit()

    from backend.features.admin.admin_handler import _show_private_admin_menu

    await _show_private_admin_menu(update, context, target_chat_id)
