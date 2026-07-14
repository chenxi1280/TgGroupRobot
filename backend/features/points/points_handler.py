from __future__ import annotations

import datetime as dt
import re
from types import SimpleNamespace
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import selectinload

from backend.features.points.points_command_actions import (
    handle_balance_action,
    handle_leaderboard_action,
    handle_sign_in_action,
)
from backend.features.points.points_mall_actions import (
    handle_mall_callback_action,
    show_mall_catalog_action,
)
from backend.features.points.points_message_actions import handle_message_points_action
from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.services.command_config_service import ensure_command_enabled
from backend.features.admin.ui.points_extended import user_points_mall_keyboard
from backend.shared.services.chat_service import (
    build_points_alias_patterns,
    ensure_chat,
    get_chat_settings,
)
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.features.points.services.points_service import (
    add_message_points,
    change_points,
    format_balance_message,
    format_daily_points_leaderboard_message,
    format_leaderboard_message,
    format_sign_in_already_message,
    format_sign_in_success_message,
    get_balance,
    get_daily_points_leaderboard,
    get_leaderboard,
    get_user_rank,
    sign_in,
)
from backend.shared.services.user_service import ensure_user
_SHOULD_SEND_LEVEL_BLOCK_NOTICE_THRESHOLD_1000 = 1000
_SHOULD_SEND_LEVEL_BLOCK_NOTICE_THRESHOLD_60 = 60



class PointsHandler(BaseHandler):
    """积分 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 积分功能不需要管理员权限
        self._require_admin_permission = False

    @staticmethod
    def _should_send_level_block_notice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
        cache = context.application.bot_data.setdefault("points_level_block_notice", {})
        key = (chat_id, user_id)
        now = dt.datetime.now(dt.UTC)
        # 驱逐超过 10 分钟的旧条目，防止内存泄漏
        if len(cache) > _SHOULD_SEND_LEVEL_BLOCK_NOTICE_THRESHOLD_1000:
            cutoff = now - dt.timedelta(minutes=10)
            stale = [k for k, v in cache.items() if isinstance(v, dt.datetime) and v < cutoff]
            for k in stale:
                cache.pop(k, None)
        last_sent = cache.get(key)
        if isinstance(last_sent, dt.datetime) and (now - last_sent).total_seconds() < _SHOULD_SEND_LEVEL_BLOCK_NOTICE_THRESHOLD_60:
            return False
        cache[key] = now
        return True

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理积分回调（用于 BaseHandler 抽象方法）"""
        # PointsHandler 主要用于消息处理，不使用 process 方法
        pass

    async def handle_sign_in(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理签到"""
        await handle_sign_in_action(
            update,
            context,
            ensure_chat_func=ensure_chat,
            ensure_user_func=ensure_user,
            get_chat_settings_func=get_chat_settings,
            sign_in_func=sign_in,
            format_sign_in_success_message_func=format_sign_in_success_message,
            format_sign_in_already_message_func=format_sign_in_already_message,
        )

    async def handle_balance(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理积分余额查询"""
        await handle_balance_action(
            update,
            context,
            ensure_chat_func=ensure_chat,
            ensure_user_func=ensure_user,
            get_chat_settings_func=get_chat_settings,
            get_balance_func=get_balance,
            get_user_rank_func=get_user_rank,
            format_balance_message_func=format_balance_message,
        )

    async def handle_leaderboard(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理积分排行榜"""
        await handle_leaderboard_action(
            update,
            context,
            ensure_chat_func=ensure_chat,
            get_leaderboard_func=get_leaderboard,
            format_leaderboard_message_func=format_leaderboard_message,
        )

    async def handle_message_points(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """处理发言积分"""
        return await handle_message_points_action(
            update,
            context,
            ensure_chat_func=ensure_chat,
            ensure_user_func=ensure_user,
            get_chat_settings_func=get_chat_settings,
            points_extended_service=PointsExtendedService,
            change_points_func=change_points,
            sign_in_func=sign_in,
            get_balance_func=get_balance,
            get_user_rank_func=get_user_rank,
            get_leaderboard_func=get_leaderboard,
            get_daily_points_leaderboard_func=get_daily_points_leaderboard,
            format_sign_in_success_message_func=format_sign_in_success_message,
            format_sign_in_already_message_func=format_sign_in_already_message,
            format_balance_message_func=format_balance_message,
            format_leaderboard_message_func=format_leaderboard_message,
            format_daily_points_leaderboard_message_func=format_daily_points_leaderboard_message,
            add_message_points_func=add_message_points,
            required_level_permission_func=_required_level_permission,
            should_send_level_block_notice_func=self._should_send_level_block_notice,
            show_mall_catalog_func=self.show_mall_catalog,
        )

    async def handle_text_trigger(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        trigger_text: str,
    ) -> bool:
        """按点击者身份执行安全的群文字触发能力。"""
        trigger_update = SimpleNamespace(
            callback_query=None,
            effective_chat=update.effective_chat,
            effective_user=update.effective_user,
            effective_message=update.effective_message,
        )
        return await handle_message_points_action(
            trigger_update,
            context,
            ensure_chat_func=ensure_chat,
            ensure_user_func=ensure_user,
            get_chat_settings_func=get_chat_settings,
            points_extended_service=PointsExtendedService,
            change_points_func=change_points,
            sign_in_func=sign_in,
            get_balance_func=get_balance,
            get_user_rank_func=get_user_rank,
            get_leaderboard_func=get_leaderboard,
            get_daily_points_leaderboard_func=get_daily_points_leaderboard,
            format_sign_in_success_message_func=format_sign_in_success_message,
            format_sign_in_already_message_func=format_sign_in_already_message,
            format_balance_message_func=format_balance_message,
            format_leaderboard_message_func=format_leaderboard_message,
            format_daily_points_leaderboard_message_func=format_daily_points_leaderboard_message,
            add_message_points_func=add_message_points,
            required_level_permission_func=_required_level_permission,
            should_send_level_block_notice_func=self._should_send_level_block_notice,
            show_mall_catalog_func=self.show_mall_catalog,
            text_override=trigger_text,
            allow_admin_adjustment=False,
            allow_level_checks=False,
            allow_message_points=False,
        )

    async def show_mall_catalog(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        products=None,
        setting=None,
    ) -> None:
        await show_mall_catalog_action(
            update,
            context,
            chat_id,
            products=products,
            setting=setting,
            list_on_sale_products_func=PointsExtendedService.list_on_sale_products,
            get_or_create_mall_setting_func=PointsExtendedService.get_or_create_mall_setting,
            keyboard_builder=user_points_mall_keyboard,
        )

    async def handle_mall_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_mall_callback_action(
            update,
            context,
            ensure_chat_func=ensure_chat,
            ensure_user_func=ensure_user,
            redeem_product_func=PointsExtendedService.redeem_product,
            get_or_create_mall_setting_func=PointsExtendedService.get_or_create_mall_setting,
            list_on_sale_products_func=PointsExtendedService.list_on_sale_products,
            show_mall_catalog_func=self.show_mall_catalog,
        )


# 创建单例实例
_points_handler = PointsHandler()


# ==================== 命令处理器（适配器函数）====================

async def sign_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """签到命令"""
    allowed = await ensure_command_enabled(context, update, command_key="sign")
    if not allowed:
        return
    await _points_handler.handle_sign_in(update, context)


async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分余额命令"""
    allowed = await ensure_command_enabled(context, update, command_key="points")
    if not allowed:
        return
    await _points_handler.handle_balance(update, context)


async def points_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分排行命令"""
    allowed = await ensure_command_enabled(context, update, command_key="rank")
    if not allowed:
        return
    await _points_handler.handle_leaderboard(update, context)


async def message_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """发言积分处理器"""
    return await _points_handler.handle_message_points(update, context)


async def points_text_trigger_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, trigger_text: str) -> bool:
    return await _points_handler.handle_text_trigger(update, context, trigger_text)


async def mall_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _points_handler.handle_mall_callback(update, context)


async def alias_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分别名处理器"""
    await _points_handler.handle_balance(update, context)


async def alias_rank_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分排行别名处理器"""
    await _points_handler.handle_leaderboard(update, context)


class PointsAliasHandler:
    """积分别名动态处理器（根据配置的别名匹配）"""

    def __init__(self):
        self._patterns_cache: dict[int, dict[str, re.Pattern]] = {}

    async def _get_patterns(self, chat_id: int, db: Database) -> dict[str, re.Pattern]:
        """获取群组配置的别名正则"""
        if chat_id in self._patterns_cache:
            return self._patterns_cache[chat_id]

        async with db.session_factory() as session:
            from backend.platform.db.schema.models.core import TgChat
            from sqlalchemy import select

            # 预加载 settings 关系，避免异步上下文中的懒加载问题
            stmt = select(TgChat).options(
                selectinload(TgChat.settings)
            ).where(TgChat.id == chat_id)
            result = await session.execute(stmt)
            chat = result.scalar_one_or_none()

            if not chat or not chat.settings:
                return {}

            settings = chat.settings
            # 使用 service 层构建正则
            self._patterns_cache[chat_id] = build_points_alias_patterns(settings)
            return self._patterns_cache[chat_id]

    def clear_cache(self, chat_id: int | None = None) -> None:
        """清除缓存（配置更改后调用）"""
        if chat_id:
            self._patterns_cache.pop(chat_id, None)
        else:
            self._patterns_cache.clear()

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理别名消息"""
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        if update.effective_chat.type not in ["group", "supergroup"]:
            return

        text = update.effective_message.text
        if not text:
            return

        db: Database = context.application.bot_data["db"]
        chat_id = update.effective_chat.id

        patterns = await self._get_patterns(chat_id, db)

        # 匹配积分别名
        if patterns.get("points") and patterns["points"].match(text.strip()):
            await alias_points_handler(update, context)
            return

        # 匹配排行别名
        if patterns.get("rank") and patterns["rank"].match(text.strip()):
            await alias_rank_handler(update, context)
            return


# 全局别名处理器实例
_points_alias_handler = PointsAliasHandler()


def get_points_alias_handler() -> PointsAliasHandler:
    """获取别名处理器实例"""
    return _points_alias_handler


def _media_level_permission(message) -> str | None:
    permission_fields = {
        "allow_sticker": ("sticker",),
        "allow_audio": ("audio", "voice"),
        "allow_video": ("video",),
        "allow_photo": ("photo",),
        "allow_document": ("document",),
    }
    for permission, fields in permission_fields.items():
        if any(getattr(message, field, None) for field in fields):
            return permission
    return None


def _required_level_permission(message) -> str | None:
    media_permission = _media_level_permission(message)
    if media_permission is not None:
        return media_permission
    text = message.text or message.caption or ""
    entities = list(message.entities or []) + list(message.caption_entities or [])
    has_mention = any(entity.type in {"mention", "text_mention"} for entity in entities)
    if has_mention:
        return "allow_mention"
    if text:
        return "allow_text"
    return None
