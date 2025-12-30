from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.user_service import ensure_user


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text(t("zh-CN", "start.private"))
        return

    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        if user is not None:
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
        settings = await get_chat_settings(session, chat.id)
        await session.commit()

    await update.effective_message.reply_text(t(settings.language, "start.group"))


async def private_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理私聊中的普通文本消息"""
    if update.effective_chat is None or update.effective_message is None:
        return
    
    chat = update.effective_chat
    if chat.type != "private":
        return
    
    # 回复提示信息
    await update.effective_message.reply_text(t("zh-CN", "start.private"))





