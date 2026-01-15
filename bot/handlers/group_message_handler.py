from __future__ import annotations

import datetime as dt
import structlog

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.models.core import BannedWord
from bot.services.core.permission_service import is_user_admin
from bot.services.moderation.auto_reply_service import match_auto_reply
from bot.services.moderation.banned_word_service import match_banned_words


log = structlog.get_logger(__name__)


async def unified_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    统一的群组消息处理入口

    处理顺序：
    1. 权限判断（是否管理员）
    2. 违禁词检测（管理员跳过）
    3. 自动回复（所有人触发，包括管理员）
    """
    # 强制日志 - 必须在最开始输出，用于诊断 handler 是否被调用
    log.warning(
        "=== UNIFIED_GROUP_MESSAGE_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        message_text=(update.effective_message.text or update.effective_message.caption or "")[:50],
    )

    # 基础检查
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    # 只处理群组消息
    if chat.type == "private":
        return

    # 获取消息文本
    message_text = message.text or message.caption or ""
    if not message_text:
        return

    # 检查用户是否是管理员
    is_admin = False
    try:
        is_admin = await is_user_admin(context, chat.id, user.id)
    except Exception as e:
        log.warning("admin_check_failed", chat_id=chat.id, user_id=user.id, error=str(e))

    log.info(
        "unified_handler_admin_check",
        chat_id=chat.id,
        user_id=user.id,
        is_admin=is_admin,
    )

    db: Database = context.application.bot_data["db"]

    # 违禁词检测（管理员跳过）
    if not is_admin:
        await _process_banned_word_check(context, db, chat, user, message, message_text)
    else:
        log.info("unified_handler_skip_banned_word_admin", chat_id=chat.id, user_id=user.id)

    # 自动回复（所有人触发，包括管理员）
    await _process_auto_reply(context, db, chat, message_text)


async def _process_banned_word_check(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    message_text: str,
) -> None:
    """
    处理违禁词检测

    Args:
        context: Bot 上下文
        db: 数据库连接
        chat: 群组对象
        user: 用户对象
        message: 消息对象
        message_text: 消息文本
    """
    log.info(
        "unified_handler_banned_word_check_start",
        chat_id=chat.id,
        user_id=user.id,
        message_text_preview=message_text[:50],
    )

    async with db.session_factory() as session:
        matched_words = await match_banned_words(session, chat.id, message_text)
        await session.commit()

    log.info(
        "unified_handler_banned_word_check_result",
        chat_id=chat.id,
        user_id=user.id,
        matched_count=len(matched_words),
    )

    if matched_words:
        # 使用第一个匹配的违禁词的配置
        word = matched_words[0]

        log.info(
            "banned_word_detected",
            chat_id=chat.id,
            user_id=user.id,
            username=user.username,
            word=word.word,
            action=word.action,
        )

        # 删除消息
        try:
            await message.delete()
        except Exception as e:
            log.warning("delete_message_failed", chat_id=chat.id, user_id=user.id, error=str(e))

        # 发送提醒
        if word.notify:
            notify_msg = word.notify_message or f"🚫 您的消息因包含违禁词「{word.word}」已被删除"
            try:
                await context.bot.send_message(chat_id=chat.id, text=notify_msg)
            except Exception as e:
                log.warning("send_notify_failed", chat_id=chat.id, error=str(e))

        # 执行惩罚
        if word.action == "mute":
            try:
                until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=word.mute_duration) if word.mute_duration else None
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions={"can_send_messages": False, "can_send_media_messages": False},
                    until_date=until_date,
                )
            except Exception as e:
                log.warning("mute_user_failed", chat_id=chat.id, user_id=user.id, error=str(e))
        elif word.action == "ban":
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            except Exception as e:
                log.warning("ban_user_failed", chat_id=chat.id, user_id=user.id, error=str(e))


async def _process_auto_reply(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    message_text: str,
) -> None:
    """
    处理自动回复

    Args:
        context: Bot 上下文
        db: 数据库连接
        chat: 群组对象
        message_text: 消息文本
    """
    log.info(
        "unified_handler_auto_reply_start",
        chat_id=chat.id,
        message_text_preview=message_text[:50],
    )

    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat.id, message_text)
        await session.commit()

    log.info(
        "unified_handler_auto_reply_result",
        chat_id=chat.id,
        matched=result.success,
        has_reply_content=bool(result.reply_content),
    )

    if result.success and result.reply_content:
        try:
            await context.bot.send_message(chat_id=chat.id, text=result.reply_content)
            log.info(
                "unified_handler_auto_reply_sent",
                chat_id=chat.id,
                reply_content_preview=result.reply_content[:50],
            )
        except Exception as e:
            log.warning("auto_reply_send_failed", chat_id=chat.id, error=str(e))
