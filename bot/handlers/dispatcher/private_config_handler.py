"""私聊配置处理器

统一处理所有私聊中的配置流程，包括：
- 广告配置
- 验证配置
- 自动回复配置
- 违禁词配置
- 定时消息配置
- 接龙配置
- 邀请链接配置
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class PrivateConfigHandler:
    """私聊配置处理器

    统一处理所有私聊中的配置流程，根据用户状态类型路由到对应的配置处理器。
    """

    def __init__(self) -> None:
        """初始化私聊配置处理器"""
        # 配置处理器映射表（使用字符串状态类型）
        self._config_handlers = {
            # 有枚举定义的状态类型
            "verification_config": self._handle_verification_config,
            "auto_reply_create": self._handle_auto_reply_config,
            "banned_word_add": self._handle_banned_word_config,
            "scheduled_create": self._handle_scheduled_config,
            "lottery_create": self._handle_lottery_config,
            # 字符串状态类型（没有枚举定义）
            "ads_create_config": self._handle_ads_config,
            "solitaire_create": self._handle_solitaire_config,
            "invite_link_create": self._handle_invite_link_config,
        }

    async def handle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
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
        state_type = state.state_type

        log.info(
            "private_config_handler_entry",
            user_id=update.effective_user.id,
            state_type=state_type,
            message_text_preview=message_text[:50],
        )

        # 根据状态类型路由到对应的配置处理器
        handler = self._config_handlers.get(state_type)

        if handler:
            try:
                await handler(update, context, session, state, message_text)
            except Exception as e:
                log.exception(
                    "private_config_handler_error",
                    state_type=state_type,
                    error=str(e),
                )
                # 发送错误提示
                try:
                    await update.effective_message.reply_text(
                        f"❌ 配置处理出错: {str(e)}\n\n请使用 /cancel 取消当前配置。"
                    )
                except Exception:
                    pass
        else:
            log.warning(
                "private_config_handler_unknown_state",
                state_type=state_type,
            )

    # ==================== 各配置处理器 ====================

    async def _handle_ads_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理广告配置"""
        from bot.handlers.ads_handler import ads_create_config_message

        await ads_create_config_message(update, context)

    async def _handle_verification_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理验证配置"""
        from bot.handlers.verification_handler import verification_config_handler

        await verification_config_handler(update, context)

    async def _handle_auto_reply_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理自动回复配置"""
        from bot.handlers.auto_reply_handler import auto_reply_config_handler

        await auto_reply_config_handler(update, context)

    async def _handle_banned_word_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理违禁词配置"""
        from bot.handlers.banned_word_handler import banned_word_config_handler

        await banned_word_config_handler(update, context)

    async def _handle_scheduled_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理定时消息配置"""
        from bot.handlers.scheduled_handler import scheduled_message_handler

        await scheduled_message_handler(update, context)

    async def _handle_lottery_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理抽奖配置"""
        from bot.handlers.lottery_handler import lottery_message_handler

        await lottery_message_handler(update, context)

    async def _handle_solitaire_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理接龙配置"""
        from bot.handlers.solitaire_handler import solitaire_create_config_message

        await solitaire_create_config_message(update, context)

    async def _handle_invite_link_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        """处理邀请链接配置"""
        from bot.handlers.invite_link_handler import invite_link_create_name_message

        await invite_link_create_name_message(update, context)
