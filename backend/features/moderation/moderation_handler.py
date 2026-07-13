from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.i18n.strings import t
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.features.moderation.services.moderation_service import check_text_and_record
from backend.shared.services.user_service import ensure_user


async def _record_message(context, update, text: str):
    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        await ensure_user(
            session, user_id=user.id, username=user.username, first_name=user.first_name,
            last_name=user.last_name, language_code=user.language_code,
        )
        should_delete, _ = await check_text_and_record(
            session, settings=settings, chat_id=chat.id, user_id=user.id,
            message_id=update.effective_message.message_id, text=text,
        )
        await session.commit()
    return should_delete, settings


async def _delete_and_notify(context, update, settings) -> None:
    await update.effective_message.delete()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t(settings.language, "moderation.deleted"),
    )


async def moderation_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        return

    text = update.effective_message.text or update.effective_message.caption or ""
    if not text:
        return

    should_delete, settings = await _record_message(context, update, text)
    if should_delete:
        await _delete_and_notify(context, update, settings)


