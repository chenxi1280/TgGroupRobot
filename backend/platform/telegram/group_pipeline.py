"""群聊消息处理器

按优先级处理群聊消息：
1. 核心功能层（群控、强制关注、违禁词、自动回复）
2. 业务功能层（验证优先，然后抽奖、接龙、审核、积分）
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Awaitable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

log = structlog.get_logger(__name__)

# Handler 函数类型
HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[bool | None]]


class GroupMessageHandler:
    """群聊消息处理器

    按优先级处理群聊消息，确保各功能按正确顺序执行。
    """

    def __init__(self) -> None:
        """初始化群聊消息处理器"""
        # 延迟导入，避免循环依赖
        self._core_handler: HandlerFunc | None = None
        self._business_handlers: list[tuple[str, HandlerFunc]] | None = None

    def _get_core_handler(self) -> HandlerFunc:
        """获取核心功能处理器（懒加载）"""
        if self._core_handler is None:
            from backend.features.group_ops.group_message_handler import unified_group_message_handler

            self._core_handler = unified_group_message_handler
        return self._core_handler

    def _get_business_handlers(self) -> list[tuple[str, HandlerFunc]]:
        """获取业务功能处理器列表（懒加载）"""
        if self._business_handlers is None:
            from backend.features.activity.auction_handler import auction_group_message_handler
            from backend.features.activity.engagement_handler import engagement_message_handler
            from backend.features.activity.game_handler import game_message_handler
            from backend.features.activity.guess_handler import guess_message_handler
            from backend.features.activity.lottery_handler import lottery_message_handler
            from backend.features.moderation.moderation_handler import moderation_message_handler
            from backend.features.points.points_handler import message_points_handler
            from backend.features.activity.solitaire_handler import solitaire_join_message_handler
            from backend.features.verification.verification_handler import verify_message_handler

            self._business_handlers = [
                ("verification", verify_message_handler),
                ("auction", auction_group_message_handler),
                ("engagement", engagement_message_handler),
                ("game", game_message_handler),
                ("guess", guess_message_handler),
                ("lottery", lottery_message_handler),
                ("solitaire", solitaire_join_message_handler),
                ("moderation", moderation_message_handler),
                ("points", message_points_handler),
            ]
        return self._business_handlers

    async def handle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat: Any,
        user: Any,
        message_text: str,
    ) -> bool:
        """处理群聊消息

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            chat: 群组对象
            user: 用户对象
            message_text: 消息文本
        """
        log.info(
            "group_message_handler_entry",
            chat_id=chat.id,
            user_id=user.id,
            message_text_preview=message_text[:50],
        )

        # 核心功能（违禁词检测 + 自动回复）
        should_stop = await self._safe_execute(self._get_core_handler(), update, context, "core")
        if should_stop:
            log.info("group_message_handler_short_circuited", chat_id=chat.id, user_id=user.id)
            return True

        # 业务功能（按顺序执行）
        for name, handler in self._get_business_handlers():
            if await self._safe_execute(handler, update, context, name):
                log.info("group_business_handler_consumed", chat_id=chat.id, user_id=user.id, handler=name)
                return True
        return False

    async def _safe_execute(
        self,
        handler: HandlerFunc,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        handler_name: str,
    ) -> None:
        """安全执行处理器，捕获并记录异常

        Args:
            handler: 处理器函数
            update: Telegram 更新对象
            context: Bot 上下文
            handler_name: 处理器名称（用于日志）
        """
        try:
            result = await handler(update, context)
            return bool(result)
        except Exception as e:
            log.warning(
                "group_handler_failed",
                handler=handler_name,
                error=str(e),
            )
        return False
