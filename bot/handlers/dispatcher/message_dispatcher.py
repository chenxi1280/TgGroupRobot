"""统一消息分发器

根据消息来源和用户角色，将消息分发到对应的处理器。

这是所有文本消息的统一入口，确保消息按正确的顺序处理。
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.dispatcher.group_message_handler import GroupMessageHandler
from bot.handlers.dispatcher.private_config_handler import PrivateConfigHandler
from bot.handlers.start_handler import private_message_handler as private_default_handler

log = structlog.get_logger(__name__)


class MessageDispatcher:
    """统一消息分发器

    根据消息来源（私聊/群聊）和用户状态，将消息分发到对应的处理器。

    分发规则：
    - 私聊消息：优先检查用户状态，有配置状态则走配置流程，否则走默认私聊处理
    - 群聊消息：走群聊消息处理器（按优先级处理各功能）
    """

    def __init__(self) -> None:
        """初始化分发器"""
        self.private_config_handler = PrivateConfigHandler()
        self.group_message_handler = GroupMessageHandler()

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

        # 只处理文本消息
        message_text = message.text or message.caption or ""
        if not message_text:
            return

        log.info(
            "message_dispatcher_entry",
            chat_id=chat.id,
            user_id=user.id,
            chat_type=chat.type,
            message_text_preview=message_text[:50],
        )

        # 根据聊天类型分发
        if chat.type == "private":
            # 私聊消息：检查用户状态，走配置流程或默认处理
            await self._dispatch_private(update, context, chat, user, message_text)
        else:
            # 群聊消息：走群聊处理器
            await self.group_message_handler.handle(update, context, chat, user, message_text)

    async def _dispatch_private(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat,
        user,
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
        from bot.db.session import Database
        from bot.handlers.base.chat_resolver import ChatResolver
        from bot.services.state.state_service import get_user_state

        db: Database = context.application.bot_data["db"]

        # 检查用户是否有配置状态
        # 注意：配置状态存储在目标群组中，而不是私聊中
        # 所以需要先获取用户选中的群组，然后查询该群组的状态
        async with db.session_factory() as session:
            # 获取用户当前选中的群组
            target_chat_id = await ChatResolver.get_current_chat(db, user.id)

            state = None
            if target_chat_id:
                # 用目标群组ID查询配置状态
                state = await get_user_state(session, chat_id=target_chat_id, user_id=user.id)

            # 如果没找到，再尝试用私聊ID查询（支持定时消息等使用私聊ID保存状态的功能）
            if state is None:
                state = await get_user_state(session, chat_id=chat.id, user_id=user.id)

            if state is not None:
                # 有配置状态，走配置流程
                log.info(
                    "message_dispatcher_private_config",
                    user_id=user.id,
                    target_chat_id=target_chat_id,
                    state_type=state.state_type,
                )
                await self.private_config_handler.handle(
                    update, context, session, state, message_text
                )
                await session.commit()
                return

        # 无配置状态，走默认私聊处理（显示群组列表等）
        log.info("message_dispatcher_private_default", user_id=user.id)
        await private_default_handler(update, context)
