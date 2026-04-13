from __future__ import annotations

import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.activity.solitaire_shared import WAIT_CONFIG
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import set_user_state
from backend.shared.chat_context import PrivateChatContext


async def solitaire_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", {"target_chat_id": target_chat_id})
        await session.commit()

    now_local = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=8)))
    deadline_example = now_local + dt.timedelta(hours=24)
    text = (
        "➕ 创建接龙 ( /cancel 取消)\n\n"
        "请按以下格式一次性发送配置：\n\n"
        "```\n"
        "接龙标题\n"
        "描述（可选，可直接留空）\n"
        "最大人数: 0（0=无限制）\n"
        "参与积分: 0（0=无限制）\n"
        "截止时间: YYYY-MM-DD HH:MM（可选，可直接留空）\n"
        "```\n\n"
        "示例:\n"
        "```\n"
        "今晚聚餐\n"
        "一起吃火锅\n"
        "最大人数: 10\n"
        "参与积分: 50\n"
        f"截止时间: {deadline_example.strftime('%Y-%m-%d %H:%M')}\n"
        "```"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ 取消配置", callback_data=f"solitaire:cancel:{target_chat_id}")]]
    )
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return WAIT_CONFIG
