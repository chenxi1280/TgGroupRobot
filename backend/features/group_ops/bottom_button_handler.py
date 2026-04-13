from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.group_ops.services.bottom_button_service import get_layout
from backend.shared.callback_parser import CallbackParser
from backend.platform.telegram.errors import answer_callback_query_safely


async def bottom_button_runtime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    query = update.callback_query
    data = CallbackParser.parse(query.data or "")
    action = data.get(1)
    if action == "noop":
        await answer_callback_query_safely(update, "暂无可用按钮")
        return
    if action != "send":
        await answer_callback_query_safely(update, "暂不支持该操作")
        return

    chat_id = data.get_int_optional(2)
    layout_id = data.get_int_optional(3)
    if chat_id is None or layout_id is None:
        await answer_callback_query_safely(update, "按钮参数无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        layout = await get_layout(session, chat_id, layout_id)
        await session.commit()
    if layout is None:
        await answer_callback_query_safely(update, "按钮已失效", show_alert=True)
        return

    payload = layout.payload_text or layout.button_text
    await answer_callback_query_safely(update, f"已发送：{layout.button_text}")
    await context.bot.send_message(chat_id=chat_id, text=payload)
