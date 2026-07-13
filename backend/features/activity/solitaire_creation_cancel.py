from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from backend.features.activity.ui.solitaire import solitaire_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state
MIN_SCOPED_CALLBACK_PARTS = 3



async def solitaire_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    target_chat_id = await _resolve_cancel_chat_id(update, context)

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
def _parse_cancel_chat_id(data: str) -> int | None:
    parts = data.split(":")
    if len(parts) < MIN_SCOPED_CALLBACK_PARTS:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


async def _resolve_cancel_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    chat = update.effective_chat
    parsed_chat_id = _parse_cancel_chat_id(update.callback_query.data or "")
    if parsed_chat_id is not None or chat.type != "private":
        return parsed_chat_id if parsed_chat_id is not None else chat.id
    from backend.shared.handlers.base.chat_resolver import ChatResolver

    db: Database = context.application.bot_data["db"]
    return await ChatResolver.get_current_chat(db, update.effective_user.id)
