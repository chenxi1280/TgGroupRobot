from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.features.automation.ui.ads import (
    ads_list_keyboard,
    ads_menu_keyboard,
)
from backend.features.automation.services.ad_service import (
    get_chat_ads,
    is_ad_exhausted,
    is_rotation_ad,
    should_send_ad,
)
from backend.platform.db.schema.models.core import AdCampaign


def _ads_stats_values(ads: list[AdCampaign]) -> dict[str, int]:
    return {
        "启用中": sum(map(lambda ad: bool(ad.enabled), ads)),
        "轮播任务": sum(map(is_rotation_ad, ads)),
        "已配置调度": sum(map(lambda ad: bool(ad.schedule_time or ad.start_time or ad.interval_hours), ads)),
        "当前到点": sum(map(should_send_ad, ads)),
        "已达次数上限": sum(map(is_ad_exhausted, ads)),
        "含图片": sum(map(lambda ad: bool(ad.has_image), ads)),
    }


def _format_ads_stats(ads: list[AdCampaign]) -> str:
    counters = _ads_stats_values(ads)
    lines = ["📊 轮播广告看板", "", f"总任务数: {len(ads)}"]
    lines.extend(f"{label}: {value}" for label, value in counters.items())
    lines.extend(["", "说明: 当前已支持轮播、定时开始、发送次数控制和图片投放。"])
    return "\n".join(lines)


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
        *, page: int = 0,
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

        keyboard = ads_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=_format_ads_stats(ads), reply_markup=keyboard)


_ads_handler = AdsHandler()
