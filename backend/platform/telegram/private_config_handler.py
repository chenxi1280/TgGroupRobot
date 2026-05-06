from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.telegram.private_config_registry import (
    ConfigHandler,
    build_private_config_handlers,
    handle_quick_publish_input,
)

log = structlog.get_logger(__name__)


class PrivateConfigHandler:
    """私聊配置状态分发器。"""

    def __init__(self) -> None:
        self._config_handlers: dict[str, ConfigHandler] = build_private_config_handlers()

    async def handle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理私聊配置消息

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            session: 数据库会话
            state: 用户状态对象
            message_text: 消息文本
        """
        if update.effective_user is None or update.effective_message is None:
            return

        state_type = state.state_type

        log.info(
            "private_config_handler_entry",
            user_id=update.effective_user.id,
            state_type=state_type,
        )

        handler = self._config_handlers.get(state_type)

        if handler:
            await self._execute_handler(handler, update, context, session, state, message_text, state_type)
        else:
            await self._handle_unknown_state(update, session, state, state_type)

    async def _execute_handler(
        self,
        handler: ConfigHandler,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
        state_type: str,
    ) -> None:
        """执行配置处理器，包含统一错误处理"""
        try:
            await handler(update, context, session, state, message_text)
        except Exception as e:
            log.exception("private_config_handler_error", state_type=state_type, error=str(e))
            await self._send_error_message(update, f"配置处理出错: {str(e)}")

    async def _handle_unknown_state(
        self,
        update: Update,
        session: AsyncSession,
        state: Any,
        state_type: str,
    ) -> None:
        """处理未知状态类型"""
        log.warning("private_config_handler_unknown_state", state_type=state_type)
        await self._send_error_message(update, "当前配置状态异常，已自动退出，请重新进入配置流程。")

        # 清除异常状态，避免用户被卡死
        try:
            from backend.platform.state.state_service import clear_user_state

            await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
        except Exception as e:
            log.warning("private_config_clear_unknown_state_failed", error=str(e))

    async def _send_error_message(self, update: Update, message: str) -> None:
        """发送错误提示消息"""
        try:
            await update.effective_message.reply_text(f"❌ {message}\n\n请使用 /cancel 取消当前配置。")
        except Exception as exc:
            log.warning("private_config_error_reply_failed", error=str(exc), message=message)

    async def _handle_quick_publish_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        await handle_quick_publish_input(update, context, session, state, message_text)
