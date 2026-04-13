from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database


async def handle_sign_in_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_chat_func,
    ensure_user_func,
    get_chat_settings_func,
    sign_in_func,
    format_sign_in_success_message_func,
    format_sign_in_already_message_func,
) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text("请在群组中使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    async with db.session_factory() as session:
        await ensure_chat_func(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user_func(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        settings = await get_chat_settings_func(session, chat.id)
        if not settings.sign_enabled:
            await session.commit()
            await update.effective_message.reply_text("本群未开启签到。")
            return

        result = await sign_in_func(
            session,
            chat_id=chat.id,
            user_id=user.id,
            points=settings.sign_points,
            consecutive_days=settings.sign_consecutive_days,
            consecutive_bonus=settings.sign_consecutive_bonus,
        )
        await session.commit()

    if result.success:
        msg = format_sign_in_success_message_func(
            points=settings.sign_points,
            balance=result.balance,
            consecutive_days=result.consecutive_days,
            bonus_points=result.bonus_points,
        )
    else:
        msg = format_sign_in_already_message_func(
            balance=result.balance,
            consecutive_days=result.consecutive_days,
        )
    await update.effective_message.reply_text(msg)


async def handle_balance_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_chat_func,
    ensure_user_func,
    get_chat_settings_func,
    get_balance_func,
    get_user_rank_func,
    format_balance_message_func,
) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text("请在群组中使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    async with db.session_factory() as session:
        await ensure_chat_func(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user_func(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        await get_chat_settings_func(session, chat.id)
        balance = await get_balance_func(session, chat.id, user.id)
        rank = await get_user_rank_func(session, chat.id, user.id)
        await session.commit()

    await update.effective_message.reply_text(format_balance_message_func(balance, rank))


async def handle_leaderboard_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_chat_func,
    get_leaderboard_func,
    format_leaderboard_message_func,
) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text("请在群组中使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat

    async with db.session_factory() as session:
        await ensure_chat_func(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        leaderboard = await get_leaderboard_func(session, chat.id, limit=10)
        await session.commit()

    await update.effective_message.reply_text(format_leaderboard_message_func(leaderboard))
