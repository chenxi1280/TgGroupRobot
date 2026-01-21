"""群聊消息处理器

按优先级处理群聊消息：
1. 核心功能层（违禁词检测、自动回复、验证检查）
2. 业务功能层（抽奖参与、接龙参与、积分处理等）
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

log = structlog.get_logger(__name__)


class GroupMessageHandler:
    """群聊消息处理器

    按优先级处理群聊消息，确保各功能按正确顺序执行。
    """

    def __init__(self) -> None:
        """初始化群聊消息处理器"""
        pass

    async def handle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat,
        user,
        message_text: str,
    ) -> None:
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

        # 按优先级调用各功能处理器
        await self._process_core_features(update, context, chat, user, message_text)
        await self._process_business_features(update, context, chat, user, message_text)

    async def _process_core_features(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat,
        user,
        message_text: str,
    ) -> None:
        """处理核心功能（最高优先级）

        包括：
        - 违禁词检测
        - 自动回复
        """
        from bot.handlers.group_message_handler import (
            unified_group_message_handler,
        )

        # 统一的群组消息处理入口（违禁词检测 + 自动回复）
        await unified_group_message_handler(update, context)

    async def _process_business_features(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat,
        user,
        message_text: str,
    ) -> None:
        """处理业务功能

        按顺序调用各业务功能处理器：
        1. 验证消息处理
        2. 抽奖参与
        3. 接龙参与
        4. 定时消息处理
        5. 内容审核
        6. 积分处理
        """
        # 注意：这些处理器会按顺序调用，每个处理器内部判断是否处理该消息

        # 验证消息处理
        from bot.handlers.verification_handler import verify_message_handler

        try:
            await verify_message_handler(update, context)
        except Exception as e:
            log.warning("verify_message_handler_failed", error=str(e))

        # 抽奖参与
        from bot.handlers.lottery_handler import lottery_message_handler

        try:
            await lottery_message_handler(update, context)
        except Exception as e:
            log.warning("lottery_message_handler_failed", error=str(e))

        # 接龙参与
        from bot.handlers.solitaire_handler import solitaire_join_message_handler

        try:
            await solitaire_join_message_handler(update, context)
        except Exception as e:
            log.warning("solitaire_join_message_handler_failed", error=str(e))

        # 定时消息处理
        from bot.handlers.scheduled_handler import scheduled_message_handler

        try:
            await scheduled_message_handler(update, context)
        except Exception as e:
            log.warning("scheduled_message_handler_failed", error=str(e))

        # 内容审核
        from bot.handlers.moderation_handler import moderation_message_handler

        try:
            await moderation_message_handler(update, context)
        except Exception as e:
            log.warning("moderation_message_handler_failed", error=str(e))

        # 积分处理
        from bot.handlers.points_handler import message_points_handler

        try:
            await message_points_handler(update, context)
        except Exception as e:
            log.warning("message_points_handler_failed", error=str(e))
