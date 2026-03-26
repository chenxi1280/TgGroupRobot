"""私聊上下文辅助工具

提供私聊场景下的上下文管理功能，包括：
- 目标群组 ID 解析（支持从 callback_data 提取）
- 私聊/群聊场景统一处理
- 权限检查集成
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.services.integration.chat_group_service import get_user_current_chat
from bot.services.core.permission_service import is_user_admin
from bot.utils.callback_parser import CallbackParser

log = structlog.get_logger(__name__)


class PrivateChatContext:
    """私聊上下文辅助类

    提供私聊场景下的上下文解析和管理功能。
    """

    @staticmethod
    async def get_current_chat(
        db: Database,
        user_id: int,
    ) -> int | None:
        """获取用户当前管理的群组

        Args:
            db: 数据库实例
            user_id: 用户 ID

        Returns:
            int | None: 当前群组 ID，如果未选择返回 None
        """
        return await get_user_current_chat(db, user_id)

    @staticmethod
    async def require_current_chat(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error_message: str = "请先选择一个群组",
    ) -> int | None:
        """获取当前群组（必须存在，否则发送错误消息）

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            error_message: 未选择群组时的错误提示

        Returns:
            int | None: 当前群组 ID，如果未选择返回 None（已发送错误消息）
        """
        if update.effective_user is None or update.effective_message is None:
            return None

        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, update.effective_user.id)

        if target_chat_id is None:
            await update.effective_message.reply_text(error_message)
            return None

        return target_chat_id

    @staticmethod
    async def resolve_target_chat_from_callback(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_index: int = 2,
        *,
        allow_fallback_to_current_chat: bool = True,
    ) -> int | None:
        """从 callback_data 解析目标群组 ID

        优先从 callback_data 中提取群组 ID，如果没有则从数据库获取当前群组。

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            chat_index: callback_data 中群组 ID 的索引位置（默认 2）

        Returns:
            int | None: 目标群组 ID，如果解析失败返回 None

        Example:
            >>> # callback_data 格式: "action:subaction:chat_id:..."
            >>> target_chat_id = await PrivateChatContext.resolve_target_chat_from_callback(update, context)
        """
        if update.callback_query is None or update.effective_user is None:
            return None

        data = update.callback_query.data or ""
        cb = CallbackParser.parse(data)
        if chat_index < cb.length():
            target_chat_id = cb.get_int_optional(chat_index)
            if target_chat_id in {None, 0}:
                log.warning(
                    "invalid_target_chat_in_callback",
                    callback_data=data,
                    chat_index=chat_index,
                    user_id=update.effective_user.id,
                )
                return None
            return target_chat_id

        target_chat_id = None
        if allow_fallback_to_current_chat:
            db: Database = context.application.bot_data["db"]
            target_chat_id = await get_user_current_chat(db, update.effective_user.id)

        return target_chat_id

    @staticmethod
    async def resolve_target_chat_with_permission_check(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int | None = None,
        chat_index: int = 2,
        error_message_select_chat: str = "请先选择一个群组",
        error_message_no_permission: str = "你没有该群组的管理权限",
    ) -> int | None:
        """解析目标群组 ID 并检查管理员权限

        统一处理私聊/群聊场景：
        - 私聊场景：从 callback_data 或数据库获取群组 ID，并检查权限
        - 群聊场景：直接使用当前群组 ID，并检查权限

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            target_chat_id: 已知的目标群组 ID（可选）
            chat_index: callback_data 中群组 ID 的索引位置
            error_message_select_chat: 未选择群组时的错误提示
            error_message_no_permission: 无权限时的错误提示

        Returns:
            int | None: 目标群组 ID，如果失败返回 None（已发送错误消息）

        Example:
            >>> target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
            ...     update, context
            ... )
            >>> if target_chat_id is None:
            ...     return  # 错误消息已发送
        """
        if update.effective_chat is None or update.effective_user is None:
            return None

        chat = update.effective_chat
        user = update.effective_user

        # 群聊场景：直接使用当前群组
        if chat.type != "private":
            if not await is_user_admin(context, chat.id, user.id):
                if update.effective_message:
                    await update.effective_message.reply_text(error_message_no_permission)
                return None
            return chat.id

        # 私聊场景：解析目标群组
        if target_chat_id is None:
            # 尝试从 callback_data 解析
            if update.callback_query:
                target_chat_id = await PrivateChatContext.resolve_target_chat_from_callback(
                    update, context, chat_index
                )

            # 如果 callback_data 中也没有，从数据库获取
            if target_chat_id is None or target_chat_id == 0:
                db: Database = context.application.bot_data["db"]
                target_chat_id = await get_user_current_chat(db, user.id)

        # 检查是否获取到群组 ID
        if target_chat_id is None or target_chat_id == 0:
            if update.callback_query:
                await update.callback_query.answer(error_message_select_chat, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(error_message_select_chat)
            return None

        # 检查管理员权限
        if not await is_user_admin(context, target_chat_id, user.id):
            if update.callback_query:
                await update.callback_query.answer(error_message_no_permission, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(error_message_no_permission)
            return None

        return target_chat_id
