from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from backend.features.activity.ui.solitaire import solitaire_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state


async def solitaire_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    parts = (q.data or "").split(":")
    if len(parts) >= 3:
        try:
            target_chat_id = int(parts[2])
        except ValueError:
            target_chat_id = None
    else:
        target_chat_id = None

    if target_chat_id is None:
        if chat.type == "private":
            from backend.shared.handlers.base.chat_resolver import ChatResolver

            db: Database = context.application.bot_data["db"]
            target_chat_id = await ChatResolver.get_current_chat(db, user.id)
        else:
            target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_chat_id = user.id if chat.type == "private" else chat.id
        await clear_user_state(session, state_chat_id, user.id)
        await session.commit()

    await q.edit_message_text(
        "已取消配置，已返回接龙管理。",
        reply_markup=solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None),
    )
    return ConversationHandler.END
