"""群组解析工具类

提供统一的群组解析接口，处理私聊/群聊差异。
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.features.group_ops.services.chat_group_service import get_user_current_chat

log = structlog.get_logger(__name__)


class ChatResolver:
    """群组解析工具类

    封私聊/群聊差异处理，统一解析目标群组 ID。
    """

    @staticmethod
    async def resolve_target_chat(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error_message: str = "请先选择一个群组",
    ) -> int | None:
        """解析目标群组 ID，处理私聊/群聊差异

        如果是在群组中触发，直接返回群组 ID；
        如果是在私聊中触发，从用户状态中获取当前选中的群组 ID。

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            error_message: 未选择群组时的错误提示

        Returns:
            int | None: 目标群组 ID，如果解析失败返回 None
        """
        chat = update.effective_chat
        if chat is None:
            return None

        # 如果是群组消息，直接使用群组 ID
        if chat.type != "private":
            return chat.id

        # 如果是私聊消息，从用户状态中获取当前管理的群组
        callback_chat_id = ChatResolver.resolve_chat_id_from_callback(update)
        if callback_chat_id is not None:
            return callback_chat_id

        db = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, update.effective_user.id)

        if target_chat_id is None:
            await MessageHelper.safe_edit(update, error_message)

        return target_chat_id

    @staticmethod
    async def require_target_chat(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error_message: str = "请先选择一个群组",
    ) -> int | None:
        """要求解析目标群组 ID，失败时发送错误提示

        与 resolve_target_chat 的区别是：失败时主动发送错误消息。

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            error_message: 未选择群组时的错误提示

        Returns:
            int | None: 目标群组 ID，如果解析失败返回 None
        """
        return await ChatResolver.resolve_target_chat(update, context, error_message)

    @staticmethod
    def is_private_chat(update: Update) -> bool:
        """判断是否为私聊消息

        Args:
            update: Telegram 更新对象

        Returns:
            bool: 是否为私聊
        """
        chat = update.effective_chat
        return chat is not None and chat.type == "private"

    @staticmethod
    def is_group_chat(update: Update) -> bool:
        """判断是否为群组消息（包括 group 和 supergroup）

        Args:
            update: Telegram 更新对象

        Returns:
            bool: 是否为群组
        """
        chat = update.effective_chat
        return chat is not None and chat.type in ("group", "supergroup")

    @staticmethod
    async def get_current_chat(db: Database, user_id: int) -> int | None:
        """获取用户当前选中的群组 ID

        这是 get_user_current_chat 的统一入口封装。

        Args:
            db: 数据库实例
            user_id: 用户 ID

        Returns:
            int | None: 当前选中的群组 ID，未选中时返回 None
        """
        from backend.features.group_ops.services.chat_group_service import get_user_current_chat
        return await get_user_current_chat(db, user_id)

    @staticmethod
    def resolve_chat_id_from_callback(update: Update) -> int | None:
        """Best-effort extraction of an explicit chat id from callback_data."""
        if update.callback_query is None:
            return None
        parts = (update.callback_query.data or "").split(":")
        for index in (2, 3):
            if index >= len(parts):
                continue
            try:
                value = int(parts[index])
            except ValueError:
                continue
            if value < 0:
                return value
        return None
