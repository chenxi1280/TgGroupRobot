"""统一消息分发器

根据消息来源和用户角色，将消息分发到对应的处理器。

分发规则：
- 私聊消息：优先检查用户状态，有配置状态则走配置流程，否则走默认私聊处理
- 群聊消息：走群聊消息处理器（按优先级处理各功能）
"""
from __future__ import annotations

from typing import Any

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.chat_resolver import ChatResolver
from bot.handlers.dispatcher.group_message_handler import GroupMessageHandler
from bot.handlers.dispatcher.private_config_handler import PrivateConfigHandler
from bot.handlers.start_handler import private_message_handler as private_default_handler
from bot.services.state.state_service import get_user_state

log = structlog.get_logger(__name__)


class MessageDispatcher:
    """统一消息分发器

    根据消息来源（私聊/群聊）和用户状态，将消息分发到对应的处理器。
    """

    def __init__(self) -> None:
        """初始化分发器"""
        self._private_config_handler = PrivateConfigHandler()
        self._group_message_handler = GroupMessageHandler()

    async def dispatch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """分发消息到对应的处理器

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
        """
        # 基础检查
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        chat = update.effective_chat
        user = update.effective_user
        message = update.effective_message

        # 文本消息（媒体消息通常没有 text，但可能有 caption）
        message_text = message.text or message.caption or ""

        log.info(
            "message_dispatcher_entry",
            chat_id=chat.id,
            user_id=user.id,
            chat_type=chat.type,
        )

        # 根据聊天类型分发
        if chat.type == "private":
            await self._dispatch_private(update, context, chat, user, message_text)
        elif message_text:
            # 群聊只处理文本消息
            await self._group_message_handler.handle(update, context, chat, user, message_text)

    async def _dispatch_private(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat: Any,
        user: Any,
        message_text: str,
    ) -> None:
        """分发私聊消息

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            chat: 聊天对象
            user: 用户对象
            message_text: 消息文本
        """
        db: Database = context.application.bot_data["db"]

        async with db.session_factory() as session:
            # 获取用户状态（优先查询目标群组，其次查询私聊）
            state = await self._get_user_state(session, db, user.id, chat.id)

            if state is not None:
                # 有配置状态，走配置流程
                log.info(
                    "message_dispatcher_private_config",
                    user_id=user.id,
                    state_type=state.state_type,
                )
                await self._private_config_handler.handle(update, context, session, state, message_text)
                await session.commit()
                return

        # 私聊中的非文本且无配置状态：静默忽略
        if not message_text:
            return

        # 无配置状态，走默认私聊处理
        await private_default_handler(update, context)

    async def _get_user_state(self, session: Any, db: Database, user_id: int, chat_id: int) -> Any:
        """获取用户状态

        优先从目标群组查询状态，其次从私聊查询。

        Args:
            session: 数据库会话
            db: 数据库实例
            user_id: 用户 ID
            chat_id: 私聊 ID

        Returns:
            用户状态对象，如果没有则返回 None
        """
        # 获取用户当前选中的群组
        target_chat_id = await ChatResolver.get_current_chat(db, user_id)

        # 优先用目标群组ID查询配置状态
        if target_chat_id:
            state = await get_user_state(session, chat_id=target_chat_id, user_id=user_id)
            if state is not None:
                return state

        # 用私聊ID查询（支持定时消息等使用私聊ID保存状态的功能）
        return await get_user_state(session, chat_id=chat_id, user_id=user_id)
