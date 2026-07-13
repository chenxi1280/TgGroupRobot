"""权限检查工具类

提供统一的权限检查接口，消除 Handler 中重复的权限检查代码。
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.services.permission_service import is_user_admin

class PermissionHelper:
    """权限检查工具类

    封装所有权限检查逻辑，提供统一的错误处理和响应方式。
    """

    @staticmethod
    async def require_admin(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, error_message: str | None = None,
        show_alert: bool = False,
    ) -> bool:
        """检查并要求管理员权限

        如果用户不是管理员，会发送错误提示并返回 False。

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            chat_id: 要检查权限的群组 ID
            error_message: 自定义错误消息（可选，默认使用 i18n 字符串）
            show_alert: 是否以 alert 形式显示（仅对 callback 有效）

        Returns:
            bool: 用户是否有管理员权限
        """
        if await is_user_admin(context, chat_id, update.effective_user.id):
            return True
        message = error_message or "需要管理员权限。"
        await PermissionHelper._send_denied_message(update, message, show_alert=show_alert)
        return False

    @staticmethod
    async def require_admin_in_chat(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error_message: str | None = None,
    ) -> bool:
        """检查用户是否为当前聊天群组的管理员

        适用于直接在群组中触发的命令或操作。

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            error_message: 自定义错误消息（可选）

        Returns:
            bool: 用户是否有管理员权限
        """
        chat = update.effective_chat
        if chat is None or chat.type == "private":
            return False

        return await PermissionHelper.require_admin(
            update,
            context,
            chat.id,
            error_message=error_message,
        )
    @staticmethod
    async def _send_denied_message(
        update: Update,
        message: str,
        *,
        show_alert: bool,
    ) -> None:
        if update.callback_query is not None:
            if show_alert:
                await update.callback_query.answer(message, show_alert=True)
                return
            await update.callback_query.edit_message_text(message)
            return
        if update.effective_message is not None:
            await update.effective_message.reply_text(message)
