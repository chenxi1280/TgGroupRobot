from __future__ import annotations

import structlog
import datetime as dt
import re
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.features.automation.ui.ads import (
    ads_create_keyboard,
    ads_detail_keyboard,
    ads_frequency_keyboard,
    ads_list_keyboard,
    ads_menu_keyboard,
)
from backend.features.automation.services.ad_service import (
    create_ad_campaign,
    delete_ad,
    get_ad,
    get_ad_next_send_time,
    get_chat_ads,
    is_ad_exhausted,
    is_rotation_ad,
    mark_ad_sent,
    should_send_ad,
    toggle_ad,
)
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService
from backend.features.group_ops.services.chat_group_service import get_user_managed_chats
from backend.shared.services.publish_service import PublishService
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.platform.db.schema.models.core import AdCampaign

from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text, mark_callback_query_answered

log = structlog.get_logger(__name__)


class AdsHandler(BaseHandler):
    """广告 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 关闭默认权限检查，因为我们在各个方法中自己处理
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理广告回调（用于 BaseHandler 抽象方法）"""
        # AdsHandler 不使用 process 方法，直接调用各个方法
        pass

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """显示轮播广告菜单"""
        text = (
            "🎠 轮播广告\n\n"
            "支持单次推送、定时开始、间隔轮播和图片广告配置。"
        )
        keyboard = ads_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        page: int = 0,
    ) -> None:
        """显示轮播广告列表"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            ads = await get_chat_ads(session, target_chat_id)
            await session.commit()

        if not ads:
            keyboard = ads_menu_keyboard(target_chat_id)
            await self.message_helper.safe_edit(
                update,
                text="🎠 轮播广告列表\n\n暂无任务，点击「创建轮播广告」开始。",
                reply_markup=keyboard,
            )
            return

        text = f"🎠 轮播广告列表\n\n共 {len(ads)} 条任务"
        keyboard = ads_list_keyboard(ads, target_chat_id, page)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """显示轮播广告看板"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            ads = await get_chat_ads(session, target_chat_id)
            await session.commit()

        enabled_count = sum(1 for ad in ads if ad.enabled)
        with_image_count = sum(1 for ad in ads if ad.has_image)
        scheduled_count = sum(1 for ad in ads if ad.schedule_time or ad.start_time or ad.interval_hours)
        rotation_count = sum(1 for ad in ads if is_rotation_ad(ad))
        due_count = sum(1 for ad in ads if should_send_ad(ad))
        exhausted_count = sum(1 for ad in ads if is_ad_exhausted(ad))

        text = "📊 轮播广告看板\n\n"
        text += f"总任务数: {len(ads)}\n"
        text += f"启用中: {enabled_count}\n"
        text += f"轮播任务: {rotation_count}\n"
        text += f"已配置调度: {scheduled_count}\n"
        text += f"当前到点: {due_count}\n"
        text += f"已达次数上限: {exhausted_count}\n"
        text += f"含图片: {with_image_count}\n\n"
        text += "说明: 当前已支持轮播、定时开始、发送次数控制和图片投放。"

        keyboard = ads_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


_ads_handler = AdsHandler()
