from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.points_service import get_balance, sign_in
from bot.services.user_service import ensure_user


async def sign_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(t("zh-CN", "error.need_group"))
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        settings = await get_chat_settings(session, chat.id)
        if not settings.sign_enabled:
            await session.commit()
            await update.effective_message.reply_text("本群未开启签到。")
            return

        ok, balance = await sign_in(session, chat_id=chat.id, user_id=user.id, points=settings.sign_points)
        await session.commit()

    if ok:
        await update.effective_message.reply_text(
            t(settings.language, "points.signed", points=settings.sign_points, balance=balance)
        )
    else:
        await update.effective_message.reply_text(t(settings.language, "points.already_signed", balance=balance))


async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(t("zh-CN", "error.need_group"))
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        settings = await get_chat_settings(session, chat.id)
        balance = await get_balance(session, chat.id, user.id)
        await session.commit()

    await update.effective_message.reply_text(t(settings.language, "points.balance", balance=balance))





