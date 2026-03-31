"""私聊配置处理器

统一处理所有私聊中的配置流程，根据用户状态类型路由到对应的配置处理器。

支持的配置类型：
- 广告配置
- 验证配置
- 自动回复配置
- 违禁词配置
- 接龙配置
- 邀请链接配置
- 定时消息 FSM 编辑（文本、媒体、按钮、时间）
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Awaitable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

log = structlog.get_logger(__name__)

# 配置处理器函数类型
ConfigHandler = Callable[
    [Update, ContextTypes.DEFAULT_TYPE, AsyncSession, Any, str],
    Awaitable[None],
]


class PrivateConfigHandler:
    """私聊配置处理器

    统一处理所有私聊中的配置流程，根据用户状态类型路由到对应的配置处理器。
    """

    def __init__(self) -> None:
        """初始化私聊配置处理器"""
        # 配置处理器映射表
        self._config_handlers: dict[str, ConfigHandler] = {
            # 基础配置
            "verification_config": self._handle_verification_config,
            "anti_flood_config": self._handle_anti_flood_config,
            "anti_spam_config": self._handle_anti_spam_config,
            "auto_reply_create": self._handle_auto_reply_config,
            "auto_reply_edit_keywords": self._handle_auto_reply_config,
            "auto_reply_edit_content": self._handle_auto_reply_config,
            "auto_reply_edit_cover": self._handle_auto_reply_config,
            "auto_reply_edit_buttons": self._handle_auto_reply_config,
            "banned_word_add": self._handle_banned_word_config,
            "lottery_create": self._handle_lottery_config,
            "ads_create_config": self._handle_ads_config,
            "solitaire_create": self._handle_solitaire_config,
            "invite_link_create": self._handle_invite_link_config,
            "invite_link_cover_input": self._handle_invite_link_config,
            "invite_link_text_input": self._handle_invite_link_config,
            "invite_link_buttons_input": self._handle_invite_link_config,
            "renewal_card_input": self._handle_renewal_card_input,
            "force_subscribe_channel_1_input": self._handle_force_subscribe_input,
            "force_subscribe_channel_2_input": self._handle_force_subscribe_input,
            "force_subscribe_text_input": self._handle_force_subscribe_input,
            "force_subscribe_cover_input": self._handle_force_subscribe_input,
            "force_subscribe_buttons_input": self._handle_force_subscribe_input,
            "group_lock_open_keyword_input": self._handle_group_lock_input,
            "group_lock_close_keyword_input": self._handle_group_lock_input,
            "group_lock_open_time_input": self._handle_group_lock_input,
            "group_lock_close_time_input": self._handle_group_lock_input,
            "rename_monitor_text_input": self._handle_rename_monitor_input,
            "welcome_title_input": self._handle_welcome_input,
            "welcome_text_input": self._handle_welcome_input,
            "welcome_cover_input": self._handle_welcome_input,
            "welcome_buttons_input": self._handle_welcome_input,
            "alliance_create_name_input": self._handle_alliance_input,
            "alliance_join_code_input": self._handle_alliance_input,
            "garage_forward_source_input": self._handle_garage_forward_input,
            "garage_forward_keyword_input": self._handle_garage_forward_input,
            "garage_badge_input": self._handle_garage_features_input,
            "garage_teacher_input": self._handle_garage_features_input,
            "garage_whitelist_input": self._handle_garage_features_input,
            "garage_limit_interval_input": self._handle_garage_features_input,
            "garage_limit_max_count_input": self._handle_garage_features_input,
            "teacher_search_delegate_target_input": self._handle_garage_features_input,
            "teacher_search_delegate_location_input": self._handle_garage_features_input,
            "car_review_submit_command_input": self._handle_garage_features_input,
            "car_review_rank_command_input": self._handle_garage_features_input,
            "car_review_approver_input": self._handle_garage_features_input,
            "car_review_template_input": self._handle_garage_features_input,
            "car_review_reward_points_input": self._handle_garage_features_input,
            "custom_points_name_input": self._handle_points_extended_input,
            "custom_points_rank_input": self._handle_points_extended_input,
            "custom_points_adjust_input": self._handle_points_extended_input,
            "points_level_name_input": self._handle_points_extended_input,
            "points_level_threshold_input": self._handle_points_extended_input,
            "points_mall_command_input": self._handle_points_extended_input,
            "points_mall_cover_input": self._handle_points_extended_input,
            "points_mall_product_name_input": self._handle_points_extended_input,
            "points_mall_product_price_input": self._handle_points_extended_input,
            "points_mall_product_limit_input": self._handle_points_extended_input,
            "points_mall_product_stock_input": self._handle_points_extended_input,
            "points_mall_product_fulfiller_input": self._handle_points_extended_input,
            "points_mall_product_description_input": self._handle_points_extended_input,
            "points_mall_product_sort_input": self._handle_points_extended_input,
            "points_mall_product_cover_input": self._handle_points_extended_input,
            "bottom_button_text_input": self._handle_bottom_button_input,
            "bottom_button_button_text_input": self._handle_bottom_button_input,
            "bottom_button_payload_input": self._handle_bottom_button_input,
            "game_wait_rake_ratio": self._handle_game_input,
            "game_wait_rake_owner": self._handle_game_input,
            "game_wait_auto_start_time": self._handle_game_input,
            "game_wait_auto_stop_time": self._handle_game_input,
            "guess_wait_title": self._handle_guess_input,
            "guess_wait_cover": self._handle_guess_input,
            "guess_wait_description": self._handle_guess_input,
            "guess_wait_banker": self._handle_guess_input,
            "guess_wait_pool": self._handle_guess_input,
            "guess_wait_options": self._handle_guess_input,
            "guess_wait_command": self._handle_guess_input,
            "guess_wait_deadline": self._handle_guess_input,
            "guess_wait_rake_ratio": self._handle_guess_input,
            "guess_wait_rake_owner": self._handle_guess_input,
            "engagement_wait_egg_template": self._handle_engagement_input,
            "engagement_wait_chat_target": self._handle_engagement_input,
            "engagement_wait_chat_plan": self._handle_engagement_input,
            "engagement_wait_chat_command": self._handle_engagement_input,
            "inherit_wait_token_input": self._handle_account_inherit_input,
            # 定时消息 FSM 状态
            "sm_edit_text": self._handle_scheduled_message_input,
            "sm_edit_media": self._handle_scheduled_message_media,
            "sm_edit_buttons": self._handle_scheduled_message_input,
            "sm_edit_start_at": self._handle_scheduled_message_input,
            "sm_edit_end_at": self._handle_scheduled_message_input,
            # 周边资料 FSM 状态
            "nearby_edit_price": self._handle_nearby_text_input,
            "nearby_edit_method": self._handle_nearby_text_input,
            "nearby_edit_address": self._handle_nearby_text_input,
            "nearby_edit_location": self._handle_nearby_location_input,
            # 兼容旧状态名，统一走续费卡密输入处理
            "renewal_enter_code": self._handle_renewal_card_input,
        }

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
            from bot.services.state.state_service import clear_user_state

            await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
        except Exception as e:
            log.warning("private_config_clear_unknown_state_failed", error=str(e))

    async def _send_error_message(self, update: Update, message: str) -> None:
        """发送错误提示消息"""
        try:
            await update.effective_message.reply_text(f"❌ {message}\n\n请使用 /cancel 取消当前配置。")
        except Exception:
            pass

    # ==================== 基础配置处理器 ====================

    async def _handle_ads_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
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
        state: Any,
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
        state: Any,
        message_text: str,
    ) -> None:
        """处理自动回复配置"""
        from bot.handlers.auto_reply_handler import auto_reply_config_handler

        await auto_reply_config_handler(update, context)

    async def _handle_anti_flood_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理防刷屏配置"""
        from bot.handlers.anti_flood_config_handler import anti_flood_config_message_handler

        await anti_flood_config_message_handler(update, context, session, state, message_text)

    async def _handle_anti_spam_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理反垃圾配置"""
        from bot.handlers.anti_spam_config_handler import anti_spam_config_message_handler

        await anti_spam_config_message_handler(update, context, session, state, message_text)

    async def _handle_banned_word_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理违禁词配置"""
        from bot.handlers.banned_word_handler import banned_word_config_handler

        await banned_word_config_handler(update, context)

    async def _handle_lottery_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
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
        state: Any,
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
        state: Any,
        message_text: str,
    ) -> None:
        """处理邀请链接配置"""
        from bot.handlers.invite_link_handler import (
            handle_invite_link_config_input,
            invite_link_create_name_message,
        )

        if state.state_type == "invite_link_create":
            await invite_link_create_name_message(update, context)
            return

        await handle_invite_link_config_input(update, context, session, state, message_text)

    async def _handle_renewal_card_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理续费卡密输入"""
        from bot.handlers.renewal_handler import handle_renewal_card_input

        await handle_renewal_card_input(update, context, session, state, message_text)

    async def _handle_bottom_button_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_bottom_button_input

        await handle_bottom_button_input(update, context, session, state, message_text)

    async def _handle_game_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_game_input

        await handle_game_input(update, context, session, state, message_text)

    async def _handle_guess_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_guess_input

        await handle_guess_input(update, context, session, state, message_text)

    async def _handle_engagement_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_engagement_input

        await handle_engagement_input(update, context, session, state, message_text)

    async def _handle_account_inherit_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.account_inherit_handler import handle_account_inherit_input

        await handle_account_inherit_input(update, context, session, state, message_text)

    async def _handle_force_subscribe_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_force_subscribe_channel_input

        await handle_force_subscribe_channel_input(update, context, session, state, message_text)

    async def _handle_group_lock_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_group_lock_text_input

        await handle_group_lock_text_input(update, context, session, state, message_text)

    async def _handle_rename_monitor_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_rename_monitor_text_input

        await handle_rename_monitor_text_input(update, context, session, state, message_text)

    async def _handle_welcome_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_welcome_input

        await handle_welcome_input(update, context, session, state, message_text)

    async def _handle_alliance_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_alliance_input

        await handle_alliance_input(update, context, session, state, message_text)

    async def _handle_points_extended_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_points_extended_input

        await handle_points_extended_input(update, context, session, state, message_text)

    async def _handle_garage_forward_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_garage_forward_input

        await handle_garage_forward_input(update, context, session, state, message_text)

    async def _handle_garage_features_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        from bot.handlers.admin_handler import handle_garage_features_input

        await handle_garage_features_input(update, context, session, state, message_text)

    # ==================== 定时消息 FSM 处理器 ====================

    async def _handle_scheduled_message_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理定时消息文本/按钮/时间输入"""
        from bot.handlers.scheduled_message_handler import _scheduled_message_handler

        if update.effective_user is None:
            return

        target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
        await _scheduled_message_handler.handle_fsm_input(
            update, context, target_chat_id, update.effective_user.id, message_text
        )

    async def _handle_scheduled_message_media(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理定时消息媒体输入"""
        from bot.handlers.scheduled_message_handler import _scheduled_message_handler

        if update.effective_user is None:
            return

        target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
        await _scheduled_message_handler.handle_media_input(
            update, context, target_chat_id, update.effective_user.id
        )

    async def _handle_nearby_text_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理周边资料文本输入（价格/方式/备注）"""
        from bot.handlers.nearby_handler import _nearby_handler

        await _nearby_handler.handle_fsm_text_input(
            update,
            context,
            session,
            state,
            message_text,
        )

    async def _handle_nearby_location_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        """处理周边资料定位输入"""
        from bot.handlers.nearby_handler import _nearby_handler

        await _nearby_handler.handle_fsm_location_input(
            update,
            context,
            session,
            state,
        )
