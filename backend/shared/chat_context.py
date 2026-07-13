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

from backend.platform.db.runtime.session import Database
from backend.features.group_ops.services.chat_group_service import get_user_current_chat
from backend.shared.services.permission_service import is_user_admin
from backend.shared.callback_parser import CallbackParser

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
        *, chat_index: int = 2,
        allow_fallback_to_current_chat: bool = True,
        error_message_select_chat: str = "请先选择一个群组",
        error_message_no_permission: str = "你没有该群组的管理权限",
    ) -> int | None:
        """解析私聊或群聊的目标群，并校验管理员权限。"""
        if update.effective_chat is None or update.effective_user is None:
            return None
        chat = update.effective_chat
        if chat.type != "private":
            allowed = await PrivateChatContext._require_admin(
                update,
                context,
                chat.id,
                error_message=error_message_no_permission,
            )
            return chat.id if allowed else None
        resolved_chat_id = await PrivateChatContext._resolve_private_target(
            update,
            context,
            target_chat_id,
            chat_index=chat_index,
            allow_fallback_to_current_chat=allow_fallback_to_current_chat,
        )
        if resolved_chat_id in {None, 0}:
            await PrivateChatContext._send_context_error(update, error_message_select_chat)
            return None
        if not await PrivateChatContext._require_admin(
            update,
            context,
            resolved_chat_id,
            error_message=error_message_no_permission,
        ):
            return None
        return resolved_chat_id

    @staticmethod
    async def _resolve_private_target(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int | None,
        *,
        chat_index: int,
        allow_fallback_to_current_chat: bool,
    ) -> int | None:
        if target_chat_id is not None:
            return target_chat_id
        if update.callback_query is not None:
            return await PrivateChatContext.resolve_target_chat_from_callback(
                update,
                context,
                chat_index,
                allow_fallback_to_current_chat=allow_fallback_to_current_chat,
            )
        if not allow_fallback_to_current_chat:
            return None
        db: Database = context.application.bot_data["db"]
        return await get_user_current_chat(db, update.effective_user.id)

    @staticmethod
    async def _send_context_error(update: Update, message: str) -> None:
        if update.callback_query is not None:
            await update.callback_query.answer(message, show_alert=True)
            return
        if update.effective_message is not None:
            await update.effective_message.reply_text(message)

    @staticmethod
    async def _require_admin(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *,
        error_message: str,
    ) -> bool:
        user = update.effective_user
        if user is None:
            return False
        if await is_user_admin(context, target_chat_id, user.id):
            return True
        await PrivateChatContext._send_context_error(update, error_message)
        return False
