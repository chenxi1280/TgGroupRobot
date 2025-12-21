from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.moderation_service import check_text_and_record
from bot.services.user_service import ensure_user


async def moderation_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        return

    text = update.effective_message.text or ""
    if not text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        await ensure_user(
            session,
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            language_code=update.effective_user.language_code,
        )

        should_delete, _reason = await check_text_and_record(
            session,
            settings=settings,
            chat_id=chat.id,
            user_id=update.effective_user.id,
            message_id=update.effective_message.message_id,
            text=text,
        )
        await session.commit()

    if should_delete:
        try:
            await update.effective_message.delete()
        except Exception:
            return
        # 轻提示，避免刷屏：这里只在删除后短提示一次（可扩展为按策略/频率）
        try:
            await context.bot.send_message(chat_id=chat.id, text=t(settings.language, "moderation.deleted"))
        except Exception:
            pass



