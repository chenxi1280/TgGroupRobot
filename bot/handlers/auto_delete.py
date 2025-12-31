from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes, filters

from bot.db.session import Database
from bot.services.chat_service import get_chat_settings

log = structlog.get_logger(__name__)


async def auto_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动删除系统消息处理器"""
    if update.effective_chat is None or update.effective_message is None:
        return

    # 只在群聊中处理
    if update.effective_chat.type not in ["group", "supergroup"]:
        return

    message = update.effective_message
    chat = update.effective_chat

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        # 检查是否开启自动删除
        if not settings.auto_delete_enabled:
            await session.commit()
            return

        should_delete = False

        # 检查进群消息
        if settings.auto_delete_join and message.new_chat_members:
            should_delete = True

        # 检查退群消息
        if settings.auto_delete_left and message.left_chat_member:
            should_delete = True

        # 检查置顶消息
        if settings.auto_delete_pinned and message.pinned_message:
            should_delete = True

        # 检查修改群名/头像/标题等
        if message.forum_topic_created or message.forum_topic_edited or message.forum_topic_closed:
            # Forum 相关消息
            pass
        elif message.general_forum_topic_hidden:
            pass
        elif message.users_shared or message.chat_shared:
            # 共享用户/聊天
            pass
        elif message.delete_this_message:
            pass
        elif message.is_automatic_forward:
            # 自动转发
            pass
        elif message.successful_payment:
            # 支付消息
            pass
        elif message.connected_website:
            # 连接网站
            pass
        elif message.proximity_alert_triggered:
            # 附近提醒
            pass
        elif message.voice_chat_scheduled or voice_chat_started := message.voice_chat_ended or message.voice_chat_participants_invited:
            # 语音聊天
            pass

        # 检查匿名管理员消息（没有 author 签名）
        if settings.auto_delete_anonymous:
            # 匿名管理员消息通常没有 from 字段，或者 from 是 Anonymous
            # 且消息是系统消息类型
            if message.from_user and message.from_user.is_bot:
                # 机器人消息通常是系统消息
                pass
            elif update.effective_chat.type == "supergroup" and message.from_user and message.from_user.username is None and message.from_user.id == 1087968824:
                # GroupAnonymousBot 的 ID
                should_delete = True

        # 检查修改群名
        if settings.auto_delete_title and message.new_chat_title:
            should_delete = True

        # 检查修改头像
        if settings.auto_delete_avatar and message.new_chat_photo:
            should_delete = True

        # 检查删除头像
        if settings.auto_delete_avatar and message.delete_chat_photo:
            should_delete = True

        await session.commit()

    # 删除消息
    if should_delete:
        try:
            await message.delete()
            log.debug("auto_deleted_message", chat_id=chat.id, message_id=message.message_id)
        except Exception as e:
            log.warning("auto_delete_failed", chat_id=chat.id, message_id=message.message_id, error=str(e))
