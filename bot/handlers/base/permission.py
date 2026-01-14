"""权限检查工具类

提供统一的权限检查接口，消除 Handler 中重复的权限检查代码。
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.i18n.strings import t
from bot.services.core.permission_service import is_user_admin

log = structlog.get_logger(__name__)


class PermissionHelper:
    """权限检查工具类

    封装所有权限检查逻辑，提供统一的错误处理和响应方式。
    """

    @staticmethod
    async def require_admin(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        error_message: str | None = None,
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
        if not await is_user_admin(context, chat_id, update.effective_user.id):
            if error_message is None:
                error_message = "需要管理员权限。"

            if update.callback_query:
                if show_alert:
                    await update.callback_query.answer(error_message, show_alert=True)
                else:
                    try:
                        await update.callback_query.edit_message_text(error_message)
                    except Exception as e:
                        log.warning("edit_message_failed", error=str(e))
            elif update.effective_message:
                try:
                    await update.effective_message.reply_text(error_message)
                except Exception as e:
                    log.warning("reply_message_failed", error=str(e))

            return False
        return True

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
