from __future__ import annotations

import asyncio
import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import get_settings
from bot.db.session import Database
from bot.i18n.strings import t
from bot.keyboards.common.chat_group import chat_group_list_keyboard
from bot.keyboards.common.start import create_start_guide_keyboard
from bot.models.enums import ConversationStateType
from bot.services.integration.chat_group_service import (
    format_empty_chat_list_hint,
    format_group_guide_message,
    format_private_chat_current_title,
    format_private_chat_list,
    format_private_chat_welcome,
    get_user_current_chat,
    get_user_managed_chats,
    set_user_current_chat,
)
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.state.state_service import clear_user_state, get_user_state
from bot.services.core.user_service import ensure_user


log = structlog.get_logger(__name__)


async def _send_guide_message(update: Update, context: ContextTypes.DEFAULT_TYPE, chat, user) -> None:
    """发送群组引导消息（共享逻辑）

    Args:
        update: Telegram 更新对象
        context: Bot 上下文
        chat: 群组聊天对象
        user: 用户对象
    """
    db: Database = context.application.bot_data["db"]

    # 设置当前管理的群组
    await set_user_current_chat(db, user.id, chat.id)

    # 获取配置的删除时间
    app_settings = get_settings()
    delete_delay = app_settings.group_guide_message_delete_seconds

    # 使用 keyboards 层创建键盘
    keyboard = create_start_guide_keyboard(context.bot.username)

    # 使用 service 层格式化消息
    text = format_group_guide_message(bot_username=context.bot.username)

    # 发送引导消息（使用 send_message 而不是 reply_text，因为消息会被删除）
    msg = await context.bot.send_message(
        chat_id=chat.id,
        text=text,
        reply_markup=keyboard
    )

    # 删除用户发送的消息
    try:
        await update.effective_message.delete()
    except Exception as e:
        log.warning("delete_user_message_failed", error=str(e))

    # 延迟后删除机器人消息（保持群组整洁）
    async def delete_later():
        try:
            await asyncio.sleep(delete_delay)
            await msg.delete()
        except Exception as e:
            log.warning("delete_bot_message_failed", error=str(e))

    asyncio.create_task(delete_later())


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """上下文感知的 /start：根据用户状态返回不同内容"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        # 私聊中显示群组列表
        chats = await get_user_managed_chats(db, user.id, context.bot)
        current_chat_id = await get_user_current_chat(db, user.id)

        if not chats:
            # 使用 service 层格式化消息
            await update.effective_message.reply_text(
                format_private_chat_welcome(context.bot.username, has_chats=False),
                reply_markup=chat_group_list_keyboard(chats, current_chat_id),
            )
        else:
            # 有当前选中的群组，显示该群组信息
            if current_chat_id:
                for cid, title, _ in chats:
                    if cid == current_chat_id:
                        # 使用 service 层格式化消息
                        await update.effective_message.reply_text(
                            format_private_chat_current_title(title),
                            reply_markup=chat_group_list_keyboard(chats, current_chat_id),
                        )
                        return

            # 没有选中群组，显示列表
            await update.effective_message.reply_text(
                format_private_chat_list(len(chats)),
                reply_markup=chat_group_list_keyboard(chats, current_chat_id),
            )
        return

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

        # 检查用户是否有对话状态
        state = await get_user_state(session, chat_id=chat.id, user_id=user.id)

        # 如果有状态，清除状态
        if state is not None:
            await clear_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    # 发送引导消息
    await _send_guide_message(update, context, chat, user)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消当前流程，返回首页"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text("请在群里使用该指令。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        # 清除状态
        await clear_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    # 发送引导消息
    await _send_guide_message(update, context, chat, user)


async def private_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理私聊中的普通文本消息"""
    if update.effective_chat is None or update.effective_message is None or update.effective_user is None:
        return

    chat = update.effective_chat
    if chat.type != "private":
        return

    user = update.effective_user

    # 先检查用户是否有对话状态（如抽奖创建流程）
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    # 如果有对话状态，不做处理（让其他专门的消息处理器处理）
    if state is not None:
        return

    # 没有对话状态，显示群组列表
    chats = await get_user_managed_chats(db, user.id, context.bot)
    current_chat_id = await get_user_current_chat(db, user.id)

    if not chats:
        # 使用 service 层格式化消息
        await update.effective_message.reply_text(
            format_empty_chat_list_hint(),
        )
    else:
        # 使用 service 层格式化消息
        await update.effective_message.reply_text(
            format_private_chat_list(len(chats)),
            reply_markup=chat_group_list_keyboard(chats, current_chat_id),
        )
