from __future__ import annotations

import asyncio
import io
import json
import re
import structlog
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TelegramError

from bot.config import get_settings
from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.handlers.base.chat_resolver import ChatResolver
from bot.i18n.strings import t
from bot.keyboards.admin.admin_main import (
    admin_main_menu,
    create_group_selection_keyboard,
    create_guide_keyboard,
    format_admin_main_menu_text,
    format_verification_menu_text,
    toggle_menu,
    verification_mode_menu,
)
from bot.keyboards.admin.points_extended import (
    custom_point_detail_keyboard,
    custom_points_list_keyboard,
    points_level_detail_keyboard,
    points_level_list_keyboard,
    points_mall_command_keyboard,
    points_mall_cover_keyboard,
    points_mall_home_keyboard,
    points_mall_notice_keyboard,
    points_mall_order_detail_keyboard,
    points_mall_orders_keyboard,
    points_mall_product_detail_keyboard,
    points_mall_products_keyboard,
)
from bot.services.integration.chat_group_service import get_user_managed_chats, set_user_current_chat
from bot.services.core.chat_service import ensure_chat, get_chat_settings, get_settings_toggle_rows
from bot.services.core.permission_service import PermissionPolicyService, is_user_admin
from bot.services.core.user_service import ensure_user
from bot.services.activity.points_extended_service import PointsExtendedService
from bot.services.activity.auction_service import (
    get_auction,
    format_auction_settings_text,
    get_or_create_setting as get_auction_setting,
    list_auctions,
    list_recent_auctions,
    update_setting as update_auction_setting,
)
from bot.services.activity.game_service import (
    format_game_menu_text,
    get_or_create_setting as get_game_setting,
    get_round_participants as get_game_round_participants,
    get_rake_owner_label as get_game_rake_owner_label,
    list_recent_rounds as list_recent_game_rounds,
    parse_ratio as parse_game_ratio,
    resolve_rake_owner as resolve_game_rake_owner,
    update_setting as update_game_setting,
    validate_hhmm as validate_game_hhmm,
)
from bot.services.activity.guess_service import (
    count_events_by_status,
    create_event as create_guess_event,
    format_event_preview,
    format_event_runtime,
    get_event as get_guess_event,
    get_or_create_setting as get_guess_setting,
    list_events as list_guess_events,
    parse_deadline as parse_guess_deadline,
    parse_options as parse_guess_options,
    parse_ratio as parse_guess_ratio,
    resolve_user_id as resolve_guess_user_id,
    settle_event as settle_guess_event,
    cancel_event as cancel_guess_event,
    update_setting as update_guess_setting,
)
from bot.services.activity.engagement_service import (
    archive_egg_snapshot,
    create_egg_event,
    get_chat_reward_top_users,
    get_or_create_chat_reward as get_engagement_chat_reward,
    get_egg_event,
    get_egg_event_counts,
    get_latest_running_egg_event,
    get_recent_chat_reward_claims,
    get_recent_chat_reward_stats,
    list_egg_events,
    list_egg_history,
    parse_reward_plan as parse_engagement_reward_plan,
    publish_next_clue,
    update_chat_reward as update_engagement_chat_reward,
    update_egg_event,
    update_egg_event_from_template,
)
from bot.services.base import ValidationError
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.integration.bottom_button_service import (
    add_layout_button,
    build_management_layout_preview,
    clear_layouts as clear_bottom_button_layouts,
    compact_layouts as compact_bottom_button_layouts,
    generate_buttons as generate_bottom_buttons,
    get_layout as get_bottom_button_layout,
    get_or_create_setting as get_bottom_button_setting,
    list_layouts as list_bottom_button_layouts,
    update_layout_button,
    update_setting as update_bottom_button_setting,
    delete_layout_button,
)
from bot.services.integration.account_inherit_service import build_summary as build_inherit_summary
from bot.services.state.state_service import set_user_state, clear_user_state, get_user_state
from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import answer_callback_query_safely, build_public_error_text, mark_callback_query_answered


log = structlog.get_logger(__name__)

JOIN_SPAM_RULE_VALUES = [1, 2, 3, 4, 5]
JOIN_SPAM_TIP_DELETE_VALUES = [30, 60, 120, 300]
JOIN_SELF_REVIEW_TIMEOUT_VALUES = [60, 120, 300, 600]
JOIN_BURST_WINDOW_VALUES = [10, 30, 60, 120]
JOIN_BURST_THRESHOLD_VALUES = [3, 5, 10, 15]

JOIN_SELF_REVIEW_ACTION_LABELS = {
    "reject_allow_retry": "🔁 驳回可重试",
    "reject_block": "⛔ 驳回并拉黑",
}

JOIN_BURST_TIP_MODE_LABELS = {
    "no_tip": "🔕 不提示",
    "tip_and_delete": "🧹 提示后删除",
}


def _cycle_config_value[T](current: T, options: list[T]) -> T:
    if current not in options:
        return options[0]
    idx = options.index(current)
    return options[(idx + 1) % len(options)]


def _resolve_private_admin_target_chat_id(cb: CallbackParser) -> int | None:
    """严格解析私聊管理回调中的目标群组 ID。"""
    action = cb.get(1)
    if action in {"switch_group", "back_to_main"}:
        return 0

    if action == "menu":
        if cb.length() >= 4 and cb.get(3) == "back_to_menu":
            return cb.get_int_optional(2)
        if cb.length() >= 4:
            return cb.get_int_optional(3)
        return None

    if action == "renewal":
        if cb.length() >= 4:
            return cb.get_int_optional(3)
        if cb.length() >= 3:
            return cb.get_int_optional(2)
        return None

    if cb.length() >= 3:
        return cb.get_int_optional(2)
    return None


def _resolve_private_scoped_target_chat_id(cb: CallbackParser) -> int | None:
    prefix = cb.get(0)
    if prefix == "adm":
        return _resolve_private_admin_target_chat_id(cb)

    if prefix == "ali":
        action = cb.get(1)
        if action in {"members", "invite"}:
            return cb.get_int_optional(2)
        if action in {"jointban", "leave"}:
            return cb.get_int_optional(2)
        if action in {"create", "join"}:
            return cb.get_int_optional(3)
        if action == "home":
            return cb.get_int_optional(2)
        return None

    if prefix == "gfw":
        action = cb.get(1)
        if action == "home":
            return cb.get_int_optional(2)
        if action == "audit":
            return cb.get_int_optional(2)
        if action == "keywords":
            return cb.get_int_optional(3)
        if action == "source":
            return cb.get_int_optional(3)
        if action in {"toggle", "mode"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "grg":
        action = cb.get(1)
        if action == "home":
            return cb.get_int_optional(2)
        if action in {"toggle", "badge"}:
            return cb.get_int_optional(2)
        if action in {"teacher", "wl", "summary"}:
            return cb.get_int_optional(3) if action in {"teacher", "wl"} else cb.get_int_optional(2)
        if action == "limit":
            return cb.get_int_optional(3) if cb.get(2) in {"interval", "max"} else cb.get_int_optional(2)
        return None

    if prefix == "tsearch":
        action = cb.get(1)
        if action == "home":
            return cb.get_int_optional(2)
        if action == "toggle":
            return cb.get_int_optional(3)
        if action == "attendance":
            return cb.get_int_optional(3)
        if action in {"delete_mode", "delegate"}:
            return cb.get_int_optional(2)
        if action == "open_course":
            return cb.get_int_optional(3)
        return None

    if prefix == "crv":
        action = cb.get(1)
        if action == "home":
            return cb.get_int_optional(2)
        if action in {
            "toggle",
            "mode",
            "lookup",
            "publish_target",
            "approver",
            "template",
            "reward",
            "submit_cmd",
            "rank_cmd",
            "fields",
            "reports",
            "report",
        }:
            return cb.get_int_optional(2)
        return None

    if prefix == "auc":
        action = cb.get(1)
        if action in {"home", "toggle", "perm", "points_mode", "list", "detail"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "btm":
        action = cb.get(1)
        if action in {"home", "toggle", "text", "layout", "generate", "repeat"}:
            return cb.get_int_optional(2)
        if action == "button":
            return cb.get_int_optional(2)
        return None

    if prefix == "gm":
        action = cb.get(1)
        if action in {"home", "toggle", "rake", "auto", "delete_mode", "rounds", "help", "detail"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "guess":
        action = cb.get(1)
        if action in {"home", "create", "list", "settings", "detail", "open", "cancel"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "act":
        action = cb.get(1)
        if action in {"home", "egg", "chat"}:
            return cb.get_int_optional(2)
        return None

    return None


class AdminHandler(BaseHandler):
    """管理员 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 关闭默认权限检查，因为我们在 process 中自己处理
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理管理回调"""
        q = update.callback_query
        await q.answer()
        mark_callback_query_answered(update)

        # 解析 callback data
        callback_data = CallbackParser.parse(q.data)
        prefix = callback_data.get(0)
        if prefix == "ali":
            await self._handle_alliance(update, context, target_chat_id, callback_data)
            return
        if prefix == "gfw":
            await self._handle_garage_forward(update, context, target_chat_id, callback_data)
            return
        if prefix == "grg":
            await self._handle_garage_auth(update, context, target_chat_id, callback_data)
            return
        if prefix == "tsearch":
            await self._handle_teacher_search(update, context, target_chat_id, callback_data)
            return
        if prefix == "crv":
            await self._handle_car_review(update, context, target_chat_id, callback_data)
            return
        if prefix == "auc":
            await self._handle_auction(update, context, target_chat_id, callback_data)
            return
        if prefix == "btm":
            await self._handle_bottom_button(update, context, target_chat_id, callback_data)
            return
        if prefix == "gm":
            await self._handle_game(update, context, target_chat_id, callback_data)
            return
        if prefix == "guess":
            await self._handle_guess(update, context, target_chat_id, callback_data)
            return
        if prefix == "act":
            await self._handle_engagement(update, context, target_chat_id, callback_data)
            return

        action = callback_data.get(1)

        # 根据操作类型分发
        if action == "menu":
            await self._handle_menu(update, context, target_chat_id, callback_data)
        elif action == "switch_group":
            await self._handle_switch_group(update, context)
        elif action == "select_group":
            await self._handle_select_group(update, context, target_chat_id)
        elif action == "back_to_main":
            await self._handle_back_to_main(update, context)
        elif action == "back_to_menu":
            await self._handle_back_to_menu(update, context, target_chat_id)
        elif action == "toggle":
            await self._handle_toggle(update, context, target_chat_id, callback_data)
        elif action == "vfy_config":
            await self._handle_verification_config_start(update, context, target_chat_id)
        elif action == "vfy_home":
            await self._handle_verification_home(update, context, target_chat_id, callback_data)
        elif action == "af_config":
            from bot.handlers.anti_flood_config_handler import start_anti_flood_config

            await start_anti_flood_config(update, context, target_chat_id)
        elif action == "as_config":
            from bot.handlers.anti_spam_config_handler import start_anti_spam_config

            await start_anti_spam_config(update, context, target_chat_id)
        elif action == "renewal":
            await self._handle_renewal(update, context, target_chat_id, callback_data)
        elif action == "perm":
            await self._handle_permission_policy(update, context, target_chat_id, callback_data)
        elif action == "gl":
            await self._handle_group_lock(update, context, target_chat_id, callback_data)
        elif action == "rm":
            await self._handle_rename_monitor(update, context, target_chat_id, callback_data)
        elif action == "fs":
            await self._handle_force_subscribe(update, context, target_chat_id, callback_data)
        elif action == "wel":
            await self._handle_welcome(update, context, target_chat_id, callback_data)
        elif action == "cpt":
            await self._handle_custom_points(update, context, target_chat_id, callback_data)
        elif action == "lvl":
            await self._handle_points_level(update, context, target_chat_id, callback_data)
        elif action == "mall":
            await self._handle_points_mall(update, context, target_chat_id, callback_data)
        elif action == "todo":
            await self._show_unimplemented_feature(update, context, target_chat_id, callback_data)

    async def _handle_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        """处理菜单操作"""
        menu_action = callback_data.get(2)

        # 分发到不同的子菜单处理器
        handlers = {
            "main": self._show_main_menu,
            "settings": self._show_settings_menu,
            "lottery": self._show_lottery_menu,
            "solitaire": self._show_solitaire_menu,
            "invite": self._show_invite_menu,
            "autoreply": self._show_autoreply_menu,
            "keywords": self._show_keywords_menu,
            "scheduled": self._show_scheduled_menu,
            "ads": self._show_ads_menu,
            "verification": self._show_verification_menu,
            "points": self._show_points_menu,
            "autodel": self._show_auto_delete_menu,
            "flood": self._show_anti_flood_menu,
            "antispam": self._show_antispam_menu,
            "renewal": self._show_renewal_menu,
            "control": self._show_control_permission_menu,
            "closegroup": self._show_group_lock_menu,
            "renamewatch": self._show_rename_monitor_menu,
            "forcesub": self._show_force_subscribe_menu,
            "welcome": self._show_welcome_list_menu,
            "alliance": self._show_alliance_menu,
            "garage_forward": self._show_garage_forward_prompt,
            "garage_auth": self._show_garage_auth_menu,
            "teacher_search": self._show_teacher_search_menu,
            "car_review": self._show_car_review_menu,
            "custom_points": self._show_custom_points_menu,
            "custom_points_add": self._show_custom_points_add_placeholder,
            "points_level": self._show_points_level_menu,
            "points_level_add": self._show_points_level_add_placeholder,
            "points_mall": self._show_points_mall_menu,
            "points_mall_cover": self._show_points_mall_cover_placeholder,
            "points_mall_command": self._show_points_mall_command_placeholder,
            "points_mall_products": self._show_points_mall_products_placeholder,
            "points_mall_orders": self._show_points_mall_orders_placeholder,
            "auction": self._show_auction_menu,
            "bottom_button": self._show_bottom_button_menu,
            "game": self._show_game_menu,
            "guess": self._show_guess_home,
            "engagement": self._show_engagement_home,
            "inherit": self._show_account_inherit_menu,
        }

        handler = handlers.get(menu_action, self._show_main_menu)
        await handler(update, context, chat_id)

    async def _handle_switch_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理切换群组操作"""
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        current_chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)

        await self._show_group_selection(update, chats, current_chat_id)

    async def _handle_select_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """处理选择群组操作"""
        db: Database = context.application.bot_data["db"]
        await set_user_current_chat(db, update.effective_user.id, chat_id)
        await self._show_main_menu(update, context, chat_id)

    async def _handle_back_to_main(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理返回主菜单操作"""
        db: Database = context.application.bot_data["db"]
        current_chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]
        await self._show_main_menu(update, context, current_chat_id)

    async def _handle_back_to_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """处理返回指定群组菜单操作"""
        await self._show_main_menu(update, context, chat_id)

    async def _handle_renewal(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        """处理续费入口操作"""
        sub_action = callback_data.get(2) if callback_data.length() >= 3 else "page"
        if sub_action == "input":
            from bot.handlers.renewal_handler import start_renewal_card_input

            await start_renewal_card_input(update, context, chat_id)
            return

        await self._show_renewal_menu(update, context, chat_id)

    async def _show_unimplemented_feature(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        feature_key = callback_data.get(3)
        redirect_map = {
            "auction": self._show_auction_menu,
            "game": self._show_game_menu,
            "guess": self._show_guess_home,
            "inherit": self._show_account_inherit_menu,
            "bottom_button": self._show_bottom_button_menu,
        }
        redirect = redirect_map.get(feature_key)
        if redirect is not None:
            await redirect(update, context, chat_id)
            return
        feature_meta = {
            "auction": ("💰 拍卖", "旧入口已废弃，请返回主菜单重新进入新版工作台。"),
            "game": ("🎮 游戏", "旧入口已废弃，请返回主菜单重新进入新版工作台。"),
            "guess": ("⚽ 竞猜", "旧入口已废弃，请返回主菜单重新进入新版工作台。"),
            "inherit": ("💥 炸号继承", "旧入口已废弃，请返回主菜单重新进入新版工作台。"),
            "bottom_button": ("⌨️ 底部按钮", "旧入口已废弃，请返回主菜单重新进入新版工作台。"),
        }
        feature_name, feature_desc = feature_meta.get(
            feature_key,
            ("🚧 功能开发中", "该功能当前只有设计稿，尚未实现可用链路。"),
        )
        text = "\n".join(
            [
                feature_name,
                "",
                feature_desc,
                "",
                "当前主菜单已取消错误跳转，避免把你带进不相干的模块。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回主菜单", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _handle_toggle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        """处理开关切换操作"""
        field = callback_data.get(3) if callback_data.length() >= 4 else callback_data.get(2)

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()

        await self._show_settings_menu(update, context, chat_id)

    async def _handle_custom_points(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击右侧按钮进行配置")
            return
        db: Database = context.application.bot_data["db"]
        if op == "add":
            async with db.session_factory() as session:
                item = await PointsExtendedService.create_custom_point_type(session, chat_id, update.effective_user.id)
                await session.commit()
            await self._show_custom_point_detail(update, context, chat_id, item.id)
            return
        if op == "detail":
            await self._show_custom_point_detail(update, context, chat_id, callback_data.get_int(4))
            return
        if op == "clear_confirm":
            type_id = callback_data.get_int(4)
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                await session.commit()
            if item is None:
                await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
                await self._show_custom_points_menu(update, context, chat_id)
                return
            await self.message_helper.safe_edit(
                update,
                text="\n".join(
                    [
                        "🌐 自定义积分 | 清空积分",
                        "",
                        f"积分名字：{item.name}",
                        "",
                        "确认后将把此积分类型下所有用户余额清空。",
                    ]
                ),
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("确认清空", callback_data=f"adm:cpt:{chat_id}:clear:{type_id}")],
                        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")],
                    ]
                ),
            )
            return
        if op == "toggle":
            type_id = callback_data.get_int(4)
            enabled = bool(callback_data.get_int(5))
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                if item is not None:
                    await PointsExtendedService.update_custom_point_type(session, item, enabled=enabled)
                await session.commit()
            await self._show_custom_point_detail(update, context, chat_id, type_id)
            return
        if op == "delete":
            type_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                if item is not None:
                    await PointsExtendedService.delete_custom_point_type(session, item)
                await session.commit()
            await self._show_custom_points_menu(update, context, chat_id)
            return
        if op == "delete_confirm":
            type_id = callback_data.get_int(4)
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                await session.commit()
            if item is None:
                await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
                await self._show_custom_points_menu(update, context, chat_id)
                return
            await self.message_helper.safe_edit(
                update,
                text="\n".join(
                    [
                        "🌐 自定义积分 | 删除积分",
                        "",
                        f"积分名字：{item.name}",
                        "",
                        "确认后将删除该积分类型及其全部余额记录。",
                    ]
                ),
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("确认删除", callback_data=f"adm:cpt:{chat_id}:delete:{type_id}")],
                        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")],
                    ]
                ),
            )
            return
        if op == "edit":
            field = callback_data.get(4)
            type_id = callback_data.get_int(5)
            state_type = "custom_points_name_input" if field == "name" else "custom_points_rank_input"
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type=state_type,
                    state_data={"target_chat_id": chat_id, "type_id": type_id},
                )
                await session.commit()
            prompt = "👉 现在输入积分名字：" if field == "name" else "👉 现在输入排行指令："
            await self.message_helper.safe_edit(update, text=prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")]]))
            return
        if op == "adjust":
            mode = callback_data.get(4)
            type_id = callback_data.get_int(5)
            if mode not in {"add", "deduct"}:
                await answer_callback_query_safely(update, "无效操作类型", show_alert=True)
                return
            state_type = "custom_points_adjust_input"
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type=state_type,
                    state_data={"target_chat_id": chat_id, "type_id": type_id, "mode": mode},
                )
                await session.commit()
            prompt = (
                "👉 请输入：用户ID 数量 备注(可选)\n\n"
                "例如：123456 20 活动奖励"
                if mode == "add"
                else "👉 请输入：用户ID 数量 备注(可选)\n\n例如：123456 20 管理员扣分"
            )
            await self.message_helper.safe_edit(
                update,
                text=prompt,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")]]
                ),
            )
            return
        if op == "clear":
            type_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                if item is not None:
                    cleared = await PointsExtendedService.clear_custom_points(
                        session,
                        chat_id=chat_id,
                        type_id=type_id,
                        operator_user_id=update.effective_user.id,
                        reason_note="管理员清空自定义积分",
                    )
                    await session.commit()
                    await answer_callback_query_safely(update, f"已清空 {cleared} 个账户余额")
                else:
                    await session.commit()
                    await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
            await self._show_custom_point_detail(update, context, chat_id, type_id)
            return
        if op == "export":
            type_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                logs = await PointsExtendedService.list_custom_point_ledger(
                    session,
                    chat_id=chat_id,
                    type_id=type_id,
                    limit=200,
                )
                await session.commit()
            if item is None:
                await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
                return
            if update.effective_chat is None:
                return
            output = io.StringIO()
            output.write(f"自定义积分日志导出：{item.name}\n\n")
            if not logs:
                output.write("暂无日志\n")
            else:
                for row in logs:
                    output.write(
                        f"{row.created_at.isoformat()} | user={row.user_id} | delta={row.delta} | "
                        f"operator={row.operator_user_id or '-'} | note={row.reason_note or '-'}\n"
                    )
            data = output.getvalue().encode("utf-8")
            stream = io.BytesIO(data)
            stream.name = f"custom_points_{chat_id}_{type_id}.txt"
            await update.effective_chat.send_document(document=stream, caption=f"{item.name} 操作日志")
            await answer_callback_query_safely(update, "已导出最近 200 条日志")
            return
        await answer_callback_query_safely(update, "暂未支持此项", show_alert=True)

    async def _handle_points_level(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击右侧按钮进行配置")
            return
        db: Database = context.application.bot_data["db"]
        if op == "toggle":
            field = callback_data.get(4)
            value = bool(callback_data.get_int(5))
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_level_setting(session, chat_id)
                if field == "enabled":
                    await PointsExtendedService.update_level_setting(session, setting, enabled=value)
                elif field == "exclude_teacher":
                    await PointsExtendedService.update_level_setting(session, setting, exclude_teacher_enabled=value)
                await session.commit()
            await self._show_points_level_menu(update, context, chat_id)
            return
        if op == "add":
            async with db.session_factory() as session:
                level = await PointsExtendedService.create_level(session, chat_id)
                await session.commit()
            await self._show_points_level_detail(update, context, chat_id, level.id)
            return
        if op == "detail":
            await self._show_points_level_detail(update, context, chat_id, callback_data.get_int(4))
            return
        if op == "edit":
            field = callback_data.get(4)
            level_id = callback_data.get_int(5)
            state_type = "points_level_name_input" if field == "name" else "points_level_threshold_input"
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type=state_type,
                    state_data={"target_chat_id": chat_id, "level_id": level_id},
                )
                await session.commit()
            prompt = "👉 请输入新的等级名称：" if field == "name" else "👉 请输入新的积分门槛："
            await self.message_helper.safe_edit(update, text=prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:lvl:{chat_id}:detail:{level_id}")]]))
            return
        if op == "perm":
            level_id = callback_data.get_int(4)
            perm = callback_data.get(5)
            perm_value = bool(callback_data.get_int(6))
            async with db.session_factory() as session:
                level = await PointsExtendedService.get_level(session, chat_id, level_id)
                if level is not None:
                    await PointsExtendedService.update_level(session, level, perm_name=perm, perm_value=perm_value)
                await session.commit()
            await self._show_points_level_detail(update, context, chat_id, level_id)
            return
        if op == "delete":
            level_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                levels = await PointsExtendedService.list_levels(session, chat_id)
                if len(levels) <= 1:
                    await session.commit()
                    await answer_callback_query_safely(update, "至少保留一个等级，无法删除", show_alert=True)
                    await self._show_points_level_detail(update, context, chat_id, level_id)
                    return
                level = await PointsExtendedService.get_level(session, chat_id, level_id)
                if level is not None:
                    await PointsExtendedService.delete_level(session, level)
                await session.commit()
            await self._show_points_level_menu(update, context, chat_id)
            return
        if op == "delete_confirm":
            await self._show_points_level_delete_confirm(update, context, chat_id, callback_data.get_int(4))
            return
        await answer_callback_query_safely(update, "暂未支持此项", show_alert=True)

    async def _handle_points_mall(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击可配置项继续编辑")
            return
        db: Database = context.application.bot_data["db"]
        if op == "toggle":
            field = callback_data.get(4)
            value = bool(callback_data.get_int(5))
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                if field == "enabled":
                    await PointsExtendedService.update_mall_setting(session, setting, enabled=value)
                elif field == "auto_unlist":
                    await PointsExtendedService.update_mall_setting(session, setting, auto_unlist_when_out_of_stock=value)
                await session.commit()
            await self._show_points_mall_menu(update, context, chat_id)
            return
        if op == "edit" and callback_data.get(4) == "command":
            await self._show_points_mall_command_placeholder(update, context, chat_id)
            return
        if op == "edit" and callback_data.get(4) == "notice":
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await session.commit()
            await self.message_helper.safe_edit(
                update,
                text="🧾 积分商城 | 兑换通知\n\n请选择兑换提示消息的删除方式：",
                reply_markup=points_mall_notice_keyboard(chat_id, setting.redeem_notice_delete_seconds),
            )
            return
        if op == "edit" and callback_data.get(4) == "cover":
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type="points_mall_cover_input",
                    state_data={"target_chat_id": chat_id},
                )
                await session.commit()
            await self.message_helper.safe_edit(
                update,
                text="🛍️ 积分商城 | 商城封面\n\n👉 请发送图片或视频文件，或输入 清空",
                reply_markup=points_mall_cover_keyboard(chat_id),
            )
            return
        if op == "notice":
            seconds = callback_data.get_int(4)
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    redeem_notice_delete_seconds=seconds,
                )
                await session.commit()
            await self._show_points_mall_menu(update, context, chat_id)
            return
        if op == "cover" and callback_data.get(4) == "clear":
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type=None,
                    cover_file_id=None,
                )
                await session.commit()
            await self._show_points_mall_cover_placeholder(update, context, chat_id)
            return
        if op == "orders":
            product_id = callback_data.get_int_optional(4)
            status = _normalize_mall_order_status(callback_data.get(5) or "a")
            await self._show_points_mall_orders_placeholder(update, context, chat_id, product_id=product_id, status=status)
            return
        if op == "orders_status":
            status = _normalize_mall_order_status(callback_data.get(4) or "a")
            product_id = callback_data.get_int_optional(5)
            await self._show_points_mall_orders_placeholder(update, context, chat_id, product_id=product_id, status=status)
            return
        if op == "order":
            sub = callback_data.get(4)
            order_id = callback_data.get_int(5)
            status = _normalize_mall_order_status(callback_data.get(6) or "a")
            product_token = callback_data.get_int_optional(7)
            product_id = None if product_token in {None, 0} else product_token
            if sub == "detail":
                await self._show_points_mall_order_detail(update, context, chat_id, order_id, status=status, product_id=product_id)
                return
            async with db.session_factory() as session:
                if sub == "fulfill":
                    success, message, _order = await PointsExtendedService.fulfill_order(
                        session,
                        chat_id=chat_id,
                        order_id=order_id,
                        operator_user_id=update.effective_user.id,
                    )
                elif sub == "cancel":
                    success, message, _order = await PointsExtendedService.cancel_order(
                        session,
                        chat_id=chat_id,
                        order_id=order_id,
                        operator_user_id=update.effective_user.id,
                    )
                elif sub == "refund":
                    success, message, _order = await PointsExtendedService.refund_order(
                        session,
                        chat_id=chat_id,
                        order_id=order_id,
                        operator_user_id=update.effective_user.id,
                    )
                else:
                    await session.commit()
                    await answer_callback_query_safely(update, "暂未支持此订单操作", show_alert=True)
                    return
                await session.commit()
            await answer_callback_query_safely(update, message, show_alert=not success)
            await self._show_points_mall_order_detail(update, context, chat_id, order_id, status=status, product_id=product_id)
            return
        if op == "product":
            sub = callback_data.get(4)
            if sub == "add":
                async with db.session_factory() as session:
                    product = await PointsExtendedService.create_product(session, chat_id)
                    await session.commit()
                await self._show_points_mall_product_detail(update, context, chat_id, product.product_id)
                return
            if sub == "detail":
                await self._show_points_mall_product_detail(update, context, chat_id, callback_data.get_int(5))
                return
            if sub == "preview":
                await self._show_points_mall_product_preview(update, context, chat_id, callback_data.get_int(5))
                return
            if sub == "toggle":
                product_id = callback_data.get_int(5)
                enabled = bool(callback_data.get_int(6))
                async with db.session_factory() as session:
                    product = await PointsExtendedService.get_product(session, chat_id, product_id)
                    if product is not None:
                        await PointsExtendedService.update_product_status(session, product, on_sale=enabled)
                    await session.commit()
                await self._show_points_mall_product_detail(update, context, chat_id, product_id)
                return
            if sub == "delete":
                product_id = callback_data.get_int(5)
                async with db.session_factory() as session:
                    product = await PointsExtendedService.get_product(session, chat_id, product_id)
                    if product is not None:
                        await PointsExtendedService.delete_product(session, product)
                    await session.commit()
                await self._show_points_mall_products_placeholder(update, context, chat_id)
                return
            if sub == "delete_confirm":
                product_id = callback_data.get_int(5)
                async with db.session_factory() as session:
                    product = await PointsExtendedService.get_product(session, chat_id, product_id)
                    await session.commit()
                if product is None:
                    await answer_callback_query_safely(update, "商品不存在", show_alert=True)
                    await self._show_points_mall_products_placeholder(update, context, chat_id)
                    return
                await self.message_helper.safe_edit(
                    update,
                    text="\n".join(
                        [
                            "🛍️ 管理商品 | 删除商品",
                            "",
                            f"商品名称：{product.name}",
                            f"兑换价格：{product.price_points}",
                            "",
                            "确认后将删除该商品。",
                        ]
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("确认删除", callback_data=f"adm:mall:{chat_id}:product:delete:{product_id}")],
                            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")],
                        ]
                    ),
                )
                return
            if sub == "edit":
                product_id = callback_data.get_int(5)
                field = callback_data.get(6)
                if field == "cover":
                    async with db.session_factory() as session:
                        await set_user_state(
                            session,
                            chat_id=update.effective_user.id,
                            user_id=update.effective_user.id,
                            state_type="points_mall_product_cover_input",
                            state_data={"target_chat_id": chat_id, "product_id": product_id},
                        )
                        await session.commit()
                    await self.message_helper.safe_edit(
                        update,
                        text="🛍️ 管理商品 | 上传封面\n\n👉 请发送图片或视频文件，或输入 清空",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
                        ),
                    )
                    return
                state_map = {
                    "name": ("points_mall_product_name_input", "👉 请输入商品名称："),
                    "price": ("points_mall_product_price_input", "👉 请输入所需积分："),
                    "limit": ("points_mall_product_limit_input", "👉 请输入限购次数（输入 0 表示不限购）："),
                    "stock": ("points_mall_product_stock_input", "👉 请输入可售总数量："),
                    "fulfiller": ("points_mall_product_fulfiller_input", "👉 请输入发放人员用户名或用户ID（输入 清空 取消设置）："),
                    "description": ("points_mall_product_description_input", "👉 请输入兑换说明（输入 清空 清空说明）："),
                    "sort": ("points_mall_product_sort_input", "👉 请输入排序权重："),
                }
                state_entry = state_map.get(field)
                if state_entry is None:
                    await answer_callback_query_safely(update, "暂未支持此字段", show_alert=True)
                    return
                state_type, prompt = state_entry
                async with db.session_factory() as session:
                    await set_user_state(
                        session,
                        chat_id=update.effective_user.id,
                        user_id=update.effective_user.id,
                        state_type=state_type,
                        state_data={"target_chat_id": chat_id, "product_id": product_id},
                    )
                    await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    text=prompt,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
                    ),
                )
                return
        await answer_callback_query_safely(update, "暂未支持此项", show_alert=True)

    async def _get_chat_title(self, db: Database, chat_id: int) -> str:
        """获取群组标题（优先从 Telegram API 实时获取）"""
        from bot.models.core import TgChat
        from sqlalchemy import select

        # 先从数据库查询
        async with db.session_factory() as session:
            chat_stmt = select(TgChat).where(TgChat.id == chat_id)
            chat_result = await session.execute(chat_stmt)
            chat = chat_result.scalar_one_or_none()
            db_title = chat.title if chat else None

        # 如果数据库中有标题，先尝试使用
        if db_title:
            return db_title

        # 数据库中没有标题，尝试从 Telegram API 实时获取
        try:
            tg_chat = await self.message_helper._bot.get_chat(chat_id)
            return tg_chat.title or f"群组{chat_id}"
        except (TelegramError, AttributeError, Exception):
            # 获取失败，使用数据库中的标题或回退值
            return db_title or f"群组{chat_id}"

    async def _set_current_chat(
        self,
        db: Database,
        user_id: int,
        chat_id: int,
    ) -> None:
        """设置当前管理的群组"""
        await set_user_current_chat(db, user_id, chat_id)

    # ==================== 菜单显示方法 ====================

    async def _show_main_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示主菜单"""
        db: Database = context.application.bot_data["db"]
        chat_title = await self._get_chat_title(db, chat_id)

        # 使用 keyboards 层格式化消息
        text = format_admin_main_menu_text(chat_title)
        keyboard = admin_main_menu(chat_id)

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=keyboard
        )

    async def _show_settings_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示设置菜单（已整合到主菜单）"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        await self._show_main_menu(update, context, chat_id)

    async def _show_lottery_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示抽奖管理菜单"""
        from bot.keyboards.activity.lottery import lottery_menu_keyboard
        from bot.services.activity.lottery_service import count_lotteries_by_type, get_lottery_stats

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            stats = await get_lottery_stats(session, chat_id)
            type_counts = await count_lotteries_by_type(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = f"🎁[{chat_title}]抽奖\n\n"
        text += f"创建的抽奖次数:{stats['total']}\n\n"
        text += f"已开奖:{stats['completed']}       未开奖:{stats['pending']}       取消:{stats['cancelled']}\n\n"
        text += (
            f"🎁 通用:{type_counts['common']}  "
            f"💰 积分:{type_counts['points']}  "
            f"👥 邀请:{type_counts['invite']}  "
            f"🔥 活跃:{type_counts['activity']}"
        )

        keyboard = lottery_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_solitaire_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示接龙管理菜单"""
        from bot.keyboards.activity.solitaire import solitaire_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "📋 接龙管理\n\n请选择操作："
        keyboard = solitaire_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_invite_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示邀请链接管理菜单"""
        from bot.handlers.invite_link_handler import _invite_link_handler

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        chat_title = await self._get_chat_title(db, chat_id)
        await _invite_link_handler.show_menu(update, context, chat_id, chat_title)

    async def _show_autoreply_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示自动回复管理菜单"""
        from bot.keyboards.content.auto_reply import auto_reply_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "💬 自动回复管理\n\n请选择操作："
        keyboard = auto_reply_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_keywords_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示违禁词管理菜单"""
        from bot.keyboards.content.banned_word import banned_word_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "🔇 违禁词管理\n\n请选择操作："
        keyboard = banned_word_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_scheduled_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示定时消息管理菜单"""
        from bot.handlers.scheduled_message_handler import _scheduled_message_handler

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        # 使用新版定时消息处理器显示列表
        await _scheduled_message_handler.show_list(update, context, chat_id)

    async def _show_ads_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示轮播广告菜单"""
        from bot.keyboards.content.ads import ads_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "🎠 轮播广告（基础版）\n\n请选择操作："
        keyboard = ads_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_renewal_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示续费入口"""
        from bot.handlers.renewal_handler import show_renewal_menu

        await show_renewal_menu(update, context, chat_id)

    async def _show_control_permission_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.models.enums import ControlPermissionPolicy

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        current = getattr(settings, "control_permission_policy", ControlPermissionPolicy.can_promote_members.value)
        selected = "✅"
        rows = [
            ("所有管理员", ControlPermissionPolicy.all_admins.value),
            ("拥有封禁权限", ControlPermissionPolicy.can_restrict_members.value),
            ("拥有更改群组权限", ControlPermissionPolicy.can_change_info.value),
            ("拥有添加管理员权限", ControlPermissionPolicy.can_promote_members.value),
            ("仅创建者", ControlPermissionPolicy.owner_only.value),
        ]
        buttons = []
        for label, value in rows:
            prefix = selected if current == value else "❌"
            buttons.append([InlineKeyboardButton(f"{prefix} {label}", callback_data=f"adm:perm:{chat_id}:{value}")])
        buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])

        current_label = next((label for label, value in rows if value == current), "拥有添加管理员权限")
        text = (
            "⚙️ 控制权限\n\n"
            "你可以制定哪些管理员能够设置机器人。\n\n"
            f"当前策略：{current_label}\n\n"
            "当前统一影响以下管理能力：设置页、风控页、功能工作台。"
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_group_lock_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        def on_label(v: bool) -> str:
            return "✅ 启动" if v else "启动"

        def off_label(v: bool) -> str:
            return "❌ 关闭" if not v else "关闭"

        delete_label = "删除" if getattr(settings, "group_lock_delete_notice_mode", "keep") == "delete" else "不删除"
        open_time = getattr(settings, "group_lock_open_time", None) or "未设置"
        close_time = getattr(settings, "group_lock_close_time", None) or "未设置"
        open_phrase = getattr(settings, "group_lock_open_phrase", None) or "开群了"
        close_phrase = getattr(settings, "group_lock_close_phrase", None) or "关群了"
        phrase_enabled = bool(getattr(settings, "group_lock_phrase_enabled", False))
        schedule_enabled = bool(getattr(settings, "group_lock_schedule_enabled", False))

        text = (
            "📢 关群设置\n\n"
            "根据管理员话术进行全员禁言，或者定时全员禁言，用来防范半夜管理不在是产生违规内容。\n\n"
            "话术关群：\n"
            "└ 输入开群词，打开全员聊天\n"
            "└ 输入关群词，关闭全员聊天\n"
            "└ 拥有添加管理员权限的管理员可用\n\n"
            f"⏰ 定时关群（{'已开启' if schedule_enabled else '已关闭'}）\n"
            f"└ 下次开启时间：{open_time}\n"
            f"└ 下次关停时间：{close_time}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 话术开关：", callback_data=f"adm:menu:closegroup:{chat_id}"),
                InlineKeyboardButton(on_label(phrase_enabled), callback_data=f"adm:gl:{chat_id}:set:phrase:1"),
                InlineKeyboardButton(off_label(phrase_enabled), callback_data=f"adm:gl:{chat_id}:set:phrase:0"),
            ],
            [
                InlineKeyboardButton("💬 开群词：", callback_data=f"adm:gl:{chat_id}:input:open_phrase"),
                InlineKeyboardButton(open_phrase[:12], callback_data=f"adm:gl:{chat_id}:input:open_phrase"),
            ],
            [
                InlineKeyboardButton("📢 关群词：", callback_data=f"adm:gl:{chat_id}:input:close_phrase"),
                InlineKeyboardButton(close_phrase[:12], callback_data=f"adm:gl:{chat_id}:input:close_phrase"),
            ],
            [
                InlineKeyboardButton("⚙️ 定时开关：", callback_data=f"adm:menu:closegroup:{chat_id}"),
                InlineKeyboardButton(on_label(schedule_enabled), callback_data=f"adm:gl:{chat_id}:set:schedule:1"),
                InlineKeyboardButton(off_label(schedule_enabled), callback_data=f"adm:gl:{chat_id}:set:schedule:0"),
            ],
            [
                InlineKeyboardButton("⏰ 开群时间", callback_data=f"adm:gl:{chat_id}:input:open_time"),
                InlineKeyboardButton(open_time, callback_data=f"adm:gl:{chat_id}:input:open_time"),
            ],
            [
                InlineKeyboardButton("⏰ 关群时间", callback_data=f"adm:gl:{chat_id}:input:close_time"),
                InlineKeyboardButton(close_time, callback_data=f"adm:gl:{chat_id}:input:close_time"),
            ],
            [
                InlineKeyboardButton("🧹 删除通知消息：", callback_data=f"adm:menu:closegroup:{chat_id}"),
                InlineKeyboardButton(
                    delete_label,
                    callback_data=f"adm:gl:{chat_id}:notice:{'keep' if delete_label == '删除' else 'delete'}",
                ),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_rename_monitor_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        enabled = bool(getattr(settings, "name_change_monitor_enabled", False))
        template = getattr(settings, "name_change_monitor_template_text", "") or "未设置"
        delete_after = int(getattr(settings, "name_change_monitor_delete_after_seconds", 60) or 60)
        text = (
            "🕵️ 用户改名监控\n\n"
            "当监控到用户改变昵称或者用户名，会根据本页设置发送通知到群。\n\n"
            f"状态: {'✅ 启动' if enabled else '❌ 关闭'}\n"
            f"删除提示消息: {delete_after}秒后删除\n\n"
            f"当前文案:\n{template}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:menu:renamewatch:{chat_id}"),
                InlineKeyboardButton("✅ 启用" if enabled else "启用", callback_data=f"adm:rm:{chat_id}:set:enabled:1"),
                InlineKeyboardButton("❌ 关闭" if not enabled else "关闭", callback_data=f"adm:rm:{chat_id}:set:enabled:0"),
            ],
            [InlineKeyboardButton("📝 设置提示消息", callback_data=f"adm:rm:{chat_id}:input:text")],
            [InlineKeyboardButton("🏖️ 预览效果", callback_data=f"adm:rm:{chat_id}:preview")],
            [
                InlineKeyboardButton("🧹 删除提示消息：", callback_data=f"adm:menu:renamewatch:{chat_id}"),
                InlineKeyboardButton(f"{delete_after}秒后删除", callback_data=f"adm:rm:{chat_id}:cycle_delete_after"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_force_subscribe_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.models.enums import ForceSubscribeAction

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        enabled = bool(getattr(settings, "force_subscribe_enabled", False))
        ch1 = getattr(settings, "force_subscribe_bound_channel_1", None) or "未绑定"
        ch2 = getattr(settings, "force_subscribe_bound_channel_2", None) or "未绑定"
        delete_after = int(getattr(settings, "force_subscribe_delete_warn_after_seconds", 60) or 60)
        guide_text = getattr(settings, "force_subscribe_guide_text", "") or "{member}，您需要关注我们的频道才能发言。"
        cover_set = bool(getattr(settings, "force_subscribe_cover_file_id", None))
        custom_buttons = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
        buttons = getattr(settings, "force_subscribe_buttons", None) or []
        button_summary = f"{len(buttons)} 行" if buttons else "未配置"
        check_mode = getattr(settings, "force_subscribe_check_mode", "all")
        check_mode_label = "✅ 全部频道都订阅" if check_mode == "all" else "🟡 任一频道已订阅"
        action = getattr(
            settings,
            "force_subscribe_not_subscribed_action",
            ForceSubscribeAction.delete_and_warn.value,
        )
        action_label = {
            ForceSubscribeAction.delete_and_warn.value: "删除消息并提示订阅",
            ForceSubscribeAction.delete_only.value: "仅删除消息",
            ForceSubscribeAction.warn_only.value: "仅提示订阅",
            ForceSubscribeAction.mute.value: "禁言并提示订阅",
        }.get(action, "删除消息并提示订阅")
        text = (
            "📣 强制订阅频道\n\n"
            "新用户需要订阅指定的频道，没订阅将无法发言。\n\n"
            f"状态: {'✅ 启动' if enabled else '❌ 关闭'}\n"
            f"绑定频道1: {ch1}\n"
            f"绑定频道2: {ch2}\n"
            f"设置封面: {'已设置' if cover_set else '未设置'}\n"
            f"自定义按钮: {'✅启用' if custom_buttons else '跟随频道按钮'}（{button_summary}）\n"
            f"订阅判定: {check_mode_label}\n"
            f"没订阅时处理: {action_label}\n"
            f"删除提示消息: {delete_after}秒后删除\n\n"
            f"当前文案:\n{guide_text}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:fs:{chat_id}:toggle:enabled"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:fs:{chat_id}:toggle:enabled"),
            ],
            [
                InlineKeyboardButton("⚙️ 绑定频道1：", callback_data=f"adm:fs:{chat_id}:input:channel1"),
                InlineKeyboardButton(ch1[:16], callback_data=f"adm:fs:{chat_id}:input:channel1"),
            ],
            [
                InlineKeyboardButton("⚙️ 绑定频道2：", callback_data=f"adm:fs:{chat_id}:input:channel2"),
                InlineKeyboardButton(ch2[:16], callback_data=f"adm:fs:{chat_id}:input:channel2"),
            ],
            [
                InlineKeyboardButton("🖼️ 设置封面", callback_data=f"adm:fs:{chat_id}:input:cover"),
                InlineKeyboardButton("📝 设置文案", callback_data=f"adm:fs:{chat_id}:input:text"),
            ],
            [
                InlineKeyboardButton("⌨️ 编辑自定义按钮", callback_data=f"adm:fs:{chat_id}:input:buttons"),
                InlineKeyboardButton("👀 预览效果", callback_data=f"adm:fs:{chat_id}:preview"),
            ],
            [
                InlineKeyboardButton("⚙️ 订阅判定：", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton(check_mode_label, callback_data=f"adm:fs:{chat_id}:cycle_check_mode"),
            ],
            [
                InlineKeyboardButton("⚙️ 没订阅时处理：", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton(action_label, callback_data=f"adm:fs:{chat_id}:cycle_action"),
            ],
            [
                InlineKeyboardButton("⚙️ 删除提示消息：", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton(f"{delete_after}秒后删除", callback_data=f"adm:fs:{chat_id}:cycle_delete_after"),
            ],
            [InlineKeyboardButton("🧹 清空封面", callback_data=f"adm:fs:{chat_id}:clear_cover")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_welcome_list_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.welcome_service import WelcomeService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            items = await WelcomeService.list_messages(session, chat_id)
            await session.commit()

        page_total = 1
        lines = [
            "🎉 进群欢迎",
            "",
            "新用户进群后弹出欢迎信息，支持配置多个欢迎文案。但为了减少刷屏，强烈建议只配置一个！",
            "",
        ]
        if not items:
            lines.append("0 条数据，第 1 页/共 1 页")
        else:
            for item in items:
                status = "✅ 启用" if item.enabled else "❌ 关闭"
                lines.append(f"标题：{item.title}（状态：{status}）")
                lines.append(f"┗编号：{item.id}")
                lines.append("")
            lines.append(f"{len(items)} 条数据，第 1 页/共 {page_total} 页")

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        for item in items:
            keyboard_rows.append([
                InlineKeyboardButton(f"编号:{item.id}", callback_data=f"adm:wel:{chat_id}:detail:{item.id}"),
                InlineKeyboardButton("✅启用" if item.enabled else "❌关闭", callback_data=f"adm:wel:{chat_id}:toggle:{item.id}"),
                InlineKeyboardButton("修改", callback_data=f"adm:wel:{chat_id}:detail:{item.id}"),
                InlineKeyboardButton("删除", callback_data=f"adm:wel:{chat_id}:delete:{item.id}"),
            ])
        keyboard_rows.append([InlineKeyboardButton("➕ 添加一条", callback_data=f"adm:wel:{chat_id}:add")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_welcome_detail_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        welcome_id: int,
    ) -> None:
        from bot.models.enums import WelcomeDeleteMode, WelcomeMode
        from bot.services.welcome_service import WelcomeService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await WelcomeService.get_message(session, chat_id, welcome_id)
            await session.commit()

        mode_label = "验证后欢迎" if item.welcome_mode == WelcomeMode.after_verify.value else "进群欢迎"
        delete_label = {
            WelcomeDeleteMode.keep.value: "不删除",
            WelcomeDeleteMode.delete_prev.value: "删除上一条",
            WelcomeDeleteMode.seconds.value: f"{int(item.delete_delay_seconds or 15)}秒后删除",
        }.get(item.delete_mode, "15秒后删除")
        text = (
            "🎉 进群欢迎\n\n"
            f"🧭 标题备注：{item.title}\n\n"
            f"🪩 欢迎模式：{mode_label}\n\n"
            f"🖼️ 封面设置：{'已设置' if item.cover_media_file_id else '【等待设置】'}\n\n"
            f"📄 文本内容：{item.text_content}\n\n"
            f"⭕ 设置按钮：{'【等待设置】' if not item.buttons else f'{len(item.buttons)} 行已配置'}\n\n"
            f"⏱️ 延迟删除：{delete_label}"
        )
        status_on = "✅ 启用" if item.enabled else "启用"
        status_off = "关闭" if item.enabled else "❌ 关闭"
        mode_after_verify = "✅ 验证后欢迎" if item.welcome_mode == WelcomeMode.after_verify.value else "验证后欢迎"
        mode_on_join = "进群欢迎" if item.welcome_mode == WelcomeMode.after_verify.value else "✅ 进群欢迎"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
                InlineKeyboardButton(status_on, callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
                InlineKeyboardButton(status_off, callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("⚙️ 模式：", callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
                InlineKeyboardButton(mode_after_verify, callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
                InlineKeyboardButton(mode_on_join, callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("标题备注", callback_data=f"adm:wel:{chat_id}:input:{welcome_id}:title"),
                InlineKeyboardButton("修改封面", callback_data=f"adm:wel:{chat_id}:input:{welcome_id}:cover"),
            ],
            [
                InlineKeyboardButton("修改文本", callback_data=f"adm:wel:{chat_id}:input:{welcome_id}:text"),
                InlineKeyboardButton("修改按钮", callback_data=f"adm:wel:{chat_id}:input:{welcome_id}:buttons"),
            ],
            [
                InlineKeyboardButton("🏖️ 预览效果", callback_data=f"adm:wel:{chat_id}:preview:{welcome_id}"),
                InlineKeyboardButton("⏱️ 延迟删除", callback_data=f"adm:wel:{chat_id}:cycle_delete:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("❌ 删除配置", callback_data=f"adm:wel:{chat_id}:delete:{welcome_id}"),
                InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:welcome:{chat_id}"),
            ],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_alliance_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.alliance_service import AllianceService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            alliance = await AllianceService.get_alliance_by_chat(session, chat_id)
            setting = await AllianceService.get_setting(session, chat_id)
            members = await AllianceService.list_members(session, alliance.alliance_id) if alliance is not None else []
            await session.commit()

        if alliance is None:
            text = (
                "🖐 联盟功能\n\n"
                "群组可以组建自己的联盟，在同一联盟中的群组，可以实现同步封禁等共享能力。"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 创建联盟", callback_data=f"ali:create:input:{chat_id}")],
                [InlineKeyboardButton("🤝 加入联盟", callback_data=f"ali:join:input:{chat_id}")],
                [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
            ])
            await self.message_helper.safe_edit(update, text, reply_markup=keyboard)
            return

        joint_ban_enabled = bool(setting.joint_ban_enabled) if setting is not None else False
        is_owner = alliance.owner_chat_id == chat_id
        text = (
            "🖐 联盟功能\n\n"
            f"🟩 联盟名字：{alliance.name}\n\n"
            f"👥 联盟成员：{len(members)} 个\n"
            f"联合封禁状态：{'✅ 启动' if joint_ban_enabled else '❌ 关闭'}\n\n"
            "🚫 联合封禁\n"
            "└ 联盟群使用 t 指令封禁用户，该用户加入联合封禁列表\n"
            "└ 联合封禁列表中的用户，在联盟其他群中发言，会被自动封禁\n\n"
            f"邀请码权限：{'创建群可重置' if is_owner else '仅创建群可重置'}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💥 查看联盟成员", callback_data=f"ali:members:{chat_id}")],
            [
                InlineKeyboardButton("⚙️ 联合封禁：", callback_data=f"ali:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if joint_ban_enabled else "启动", callback_data=f"ali:jointban:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if joint_ban_enabled else "✅ 关闭", callback_data=f"ali:jointban:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton(
                    "🔑 邀请密码" if is_owner else "🔑 邀请密码（仅创建群）",
                    callback_data=f"ali:invite:show:{chat_id}" if is_owner else f"ali:invite:denied:{chat_id}",
                ),
                InlineKeyboardButton("🚪 退出联盟", callback_data=f"ali:leave:{chat_id}:confirm"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_alliance_members_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.alliance_service import AllianceService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            alliance = await AllianceService.get_alliance_by_chat(session, chat_id)
            if alliance is None:
                await session.commit()
                await self._show_alliance_menu(update, context, chat_id)
                return
            members = await AllianceService.list_members(session, alliance.alliance_id)
            await session.commit()

        lines = [
            "🖐 联盟功能 | 联盟成员",
            "",
            f"联盟：{alliance.name}",
            "",
        ]
        for index, (member, chat) in enumerate(members, start=1):
            title = chat.title if chat and chat.title else str(member.chat_id)
            owner_mark = "（创建群）" if alliance.owner_chat_id == member.chat_id else ""
            lines.append(f"{index}. {title}{owner_mark}")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")]])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_garage_forward_prompt(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.garage_forward_service import GarageForwardService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await GarageForwardService.ensure_setting(session, chat_id)
            sources = await GarageForwardService.list_sources(session, chat_id)
            audit_counts = await GarageForwardService.count_audits_by_result(session, chat_id=chat_id)
            await session.commit()

        lines = [
            "🔁 车库转发",
            "",
            "此功能用来同步车库消息，防止车库被炸。",
            "支持自动同步其他车库频道的消息到当前群。",
            "",
            f"状态：{'✅ 启动' if setting.enabled else '❌ 关闭'}",
            f"同步模式：{_garage_forward_mode_label(setting.sync_mode)}",
            f"关键词规则：{('、'.join(str(item) for item in (setting.keyword_rules or [])[:8])) if setting.keyword_rules else '未配置'}",
            (
                f"审计统计：✅ 成功 {audit_counts.get('success', 0)}"
                f"｜🟡 跳过 {audit_counts.get('skipped', 0)}"
                f"｜❌ 失败 {audit_counts.get('failed', 0)}"
            ),
            "同步来源：",
        ]
        if sources:
            for item in sources:
                source_name = item.source_name or str(item.source_channel_id)
                lines.append(f"└ {source_name}（{item.source_channel_id}）")
        else:
            lines.append("└ 暂无来源频道")

        keyboard_rows = [
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"gfw:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.enabled else "启动", callback_data=f"gfw:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if setting.enabled else "❌ 关闭", callback_data=f"gfw:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 模式：", callback_data=f"gfw:home:{chat_id}"),
                InlineKeyboardButton("✅ 全部" if setting.sync_mode == "all" else "全部", callback_data=f"gfw:mode:{chat_id}:all"),
                InlineKeyboardButton(
                    "✅ 仅文本" if setting.sync_mode == "text" else "仅文本",
                    callback_data=f"gfw:mode:{chat_id}:text",
                ),
            ],
            [
                InlineKeyboardButton(
                    "✅ 仅媒体" if setting.sync_mode == "media" else "仅媒体",
                    callback_data=f"gfw:mode:{chat_id}:media",
                ),
                InlineKeyboardButton(
                    "✅ 关键词" if setting.sync_mode == "keyword" else "关键词",
                    callback_data=f"gfw:mode:{chat_id}:keyword",
                ),
            ],
            [InlineKeyboardButton("✏️ 关键词规则", callback_data=f"gfw:keywords:input:{chat_id}")],
            [InlineKeyboardButton("➕ 添加来源频道", callback_data=f"gfw:source:add:{chat_id}")],
            [InlineKeyboardButton("📜 转发日志", callback_data=f"gfw:audit:{chat_id}:a")],
        ]
        for item in sources[:10]:
            keyboard_rows.append(
                [InlineKeyboardButton(f"🗑 移除 {item.source_name or item.source_channel_id}", callback_data=f"gfw:source:remove:{chat_id}:{item.id}")]
            )
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])
        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_garage_forward_audit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        result: str = "all",
    ) -> None:
        from bot.services.integration.garage_forward_service import GarageForwardService

        normalized_result = _normalize_gfw_audit_result(result)
        title_map = {
            "all": "全部",
            "success": "成功",
            "skipped": "跳过",
            "failed": "失败",
        }
        icon_map = {
            "success": "✅",
            "skipped": "🟡",
            "failed": "❌",
        }

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            audits = await GarageForwardService.list_audits(
                session,
                chat_id=chat_id,
                result=normalized_result,
                limit=20,
            )
            counts = await GarageForwardService.count_audits_by_result(session, chat_id=chat_id)
            await session.commit()

        lines = [
            "🔁 车库转发 | 转发日志",
            "",
            f"当前筛选：{title_map.get(normalized_result, '全部')}",
            (
                f"📊 全部 {counts.get('all', 0)}"
                f"｜✅ 成功 {counts.get('success', 0)}"
                f"｜🟡 跳过 {counts.get('skipped', 0)}"
                f"｜❌ 失败 {counts.get('failed', 0)}"
            ),
            "",
        ]
        if audits:
            for item in audits:
                timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
                icon = icon_map.get(item.result, "📄")
                lines.append(
                    f"{icon} #{item.id}｜{timestamp}｜源 {item.source_channel_id}｜消息 {item.source_message_id or '-'}"
                )
                lines.append(f"动作：{item.action}｜结果：{item.result}｜原因：{item.reason or '-'}")
                lines.append("")
        else:
            lines.append("暂无日志记录")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "all" else "") + f"📋 全部({counts.get('all', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('all')}",
                ),
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "success" else "") + f"✅ 成功({counts.get('success', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('success')}",
                ),
            ],
            [
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "skipped" else "") + f"🟡 跳过({counts.get('skipped', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('skipped')}",
                ),
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "failed" else "") + f"❌ 失败({counts.get('failed', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('failed')}",
                ),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_garage_auth_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.garage_features_service import GarageAuthService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await GarageAuthService.get_settings(session, chat_id)
            teachers = await GarageAuthService.list_certified_teachers(session, chat_id)
            whitelist = await GarageAuthService.list_whitelist(session, chat_id)
            await session.commit()

        limit_mode_label = {
            "none": "关闭",
            "image": "图",
            "image_text": "文+图",
        }.get(settings.garage_limit_mode, settings.garage_limit_mode)
        partition_label = {"region": "地区", "price": "价格"}.get(settings.garage_summary_partition_by, settings.garage_summary_partition_by)
        text = (
            "🚗 车库认证\n\n"
            "自动对车库频道进行识别，需要提前找天行者进行车库对接。\n\n"
            f"状态：{'✅ 启用' if settings.garage_auth_enabled else '❌ 关闭'}\n"
            f"认证图标：{settings.garage_auth_badge}\n"
            f"手动认证老师：{len(teachers)} 人\n"
            f"限制发言：{'✅ 启用' if settings.garage_limit_enabled else '❌ 关闭'}\n"
            f"限制模式：{limit_mode_label}\n"
            f"时间间隔：{settings.garage_limit_interval_sec // 3600} 小时\n"
            f"限制条数：{settings.garage_limit_max_count} 条\n"
            f"白名单：{len(whitelist)} 人\n"
            f"分区类型：{partition_label}\n"
            f"只显开课：{'✅ 开' if settings.garage_summary_only_open_course else '❌ 关'}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"grg:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if settings.garage_auth_enabled else "启动", callback_data=f"grg:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if settings.garage_auth_enabled else "❌ 关闭", callback_data=f"grg:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 认证图标", callback_data=f"grg:badge:{chat_id}"),
                InlineKeyboardButton(settings.garage_auth_badge or "🤝", callback_data=f"grg:badge:{chat_id}"),
            ],
            [InlineKeyboardButton("💌 手动认证老师", callback_data=f"grg:teacher:list:{chat_id}:0")],
            [InlineKeyboardButton("🧾 生成老师汇总信息", callback_data=f"grg:summary:gen:{chat_id}")],
            [
                InlineKeyboardButton("⚙️ 限制发言：", callback_data=f"grg:home:{chat_id}"),
                InlineKeyboardButton("✅ 开启" if settings.garage_limit_enabled else "开启", callback_data=f"grg:limit:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if settings.garage_limit_enabled else "❌ 关闭", callback_data=f"grg:limit:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("✅ 图" if settings.garage_limit_mode == "image" else "图", callback_data=f"grg:limit:mode:{chat_id}:image"),
                InlineKeyboardButton("✅ 文+图" if settings.garage_limit_mode == "image_text" else "文+图", callback_data=f"grg:limit:mode:{chat_id}:image_text"),
                InlineKeyboardButton("✅ 关闭" if settings.garage_limit_mode == "none" else "关闭", callback_data=f"grg:limit:mode:{chat_id}:none"),
            ],
            [
                InlineKeyboardButton(f"时间间隔（{settings.garage_limit_interval_sec // 3600}小时）", callback_data=f"grg:limit:interval:{chat_id}"),
                InlineKeyboardButton(f"限制条数（{settings.garage_limit_max_count}条）", callback_data=f"grg:limit:max:{chat_id}"),
            ],
            [InlineKeyboardButton("📄 限制发言白名单", callback_data=f"grg:wl:list:{chat_id}:0")],
            [
                InlineKeyboardButton("✅ 地区" if settings.garage_summary_partition_by == "region" else "地区", callback_data=f"grg:summary:partition:{chat_id}:region"),
                InlineKeyboardButton("✅ 价格" if settings.garage_summary_partition_by == "price" else "价格", callback_data=f"grg:summary:partition:{chat_id}:price"),
            ],
            [
                InlineKeyboardButton("✅ 只显开课：开" if settings.garage_summary_only_open_course else "只显开课：开", callback_data=f"grg:summary:open:{chat_id}:1"),
                InlineKeyboardButton("只显开课：关" if settings.garage_summary_only_open_course else "✅ 只显开课：关", callback_data=f"grg:summary:open:{chat_id}:0"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_garage_teacher_list_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        page: int = 0,
    ) -> None:
        from bot.services.integration.garage_features_service import GarageAuthService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rows = await GarageAuthService.list_certified_teachers(session, chat_id)
            await session.commit()

        lines = ["🚗 车库认证 | 手动添加认证老师", "", "可以人工设置用户为认证老师，发言也会有认证图标", ""]
        if not rows:
            lines.append("数据为空")
        else:
            start = page * 10
            for item, user in rows[start:start + 10]:
                name = f"@{user.username}" if user and user.username else str(item.user_id)
                lines.append(f"- {name}")
        keyboard_rows = [[InlineKeyboardButton("➕ 添加老师", callback_data=f"grg:teacher:add:{chat_id}")]]
        for item, user in rows[page * 10: page * 10 + 10]:
            title = f"删除 {('@' + user.username) if user and user.username else item.user_id}"
            keyboard_rows.append([InlineKeyboardButton(title[:48], callback_data=f"grg:teacher:del:{chat_id}:{item.user_id}")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_garage_whitelist_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        page: int = 0,
    ) -> None:
        from bot.services.integration.garage_features_service import GarageAuthService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rows = await GarageAuthService.list_whitelist(session, chat_id)
            await session.commit()

        lines = ["📄 老师发言限制 | 添加白名单", "", "白名单中的老师可无视发言限制", ""]
        if not rows:
            lines.append("白名单为空")
        else:
            start = page * 10
            for item, user in rows[start:start + 10]:
                name = f"@{user.username}" if user and user.username else str(item.user_id)
                lines.append(f"- {name}")
        keyboard_rows = [[InlineKeyboardButton("➕ 添加白名单", callback_data=f"grg:wl:add:{chat_id}")]]
        for item, user in rows[page * 10: page * 10 + 10]:
            title = f"删除 {('@' + user.username) if user and user.username else item.user_id}"
            keyboard_rows.append([InlineKeyboardButton(title[:48], callback_data=f"grg:wl:del:{chat_id}:{item.user_id}")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_teacher_search_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.garage_features_service import TeacherSearchService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            open_teachers = await TeacherSearchService.list_open_course_teachers(session, chat_id)
            await session.commit()

        def _toggle_labels(enabled: bool) -> tuple[str, str]:
            return ("✅ 启动", "关闭") if enabled else ("启动", "✅ 关闭")

        tag_on, tag_off = _toggle_labels(setting.tag_search_enabled)
        attendance_on, attendance_off = _toggle_labels(setting.attendance_enabled)
        nearby_on, nearby_off = _toggle_labels(setting.nearby_search_enabled)
        delete_label = "不删除" if setting.delete_mode == "none" else "删除"
        footer_label = setting.footer_button_label or "无"
        text = (
            "🔎 老师搜索\n\n"
            "根据车库频道信息提供群内搜索功能，需要提前找天行者进行车库对接。\n\n"
            "标签搜索：输入车牌名称、地址、服务等信息\n"
            "附近搜索：群友发送附近可查询周边老师\n"
            "开课打卡：当日发言老师可视为开课\n"
            "强制录入：未录入位置可限制功能使用\n\n"
            f"标签搜索：{tag_on if setting.tag_search_enabled else tag_off}\n"
            f"开课打卡：{attendance_on if setting.attendance_enabled else attendance_off}\n"
            f"附近搜索：{nearby_on if setting.nearby_search_enabled else nearby_off}\n"
            f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}\n"
            f"底部按钮：{footer_label}\n"
            f"删除消息：{delete_label}\n"
            f"开课老师：{len(open_teachers)} 人"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 标签搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(tag_on, callback_data=f"tsearch:toggle:tag:{chat_id}:1"),
                InlineKeyboardButton(tag_off, callback_data=f"tsearch:toggle:tag:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 开课打卡：", callback_data=f"tsearch:attendance:menu:{chat_id}"),
                InlineKeyboardButton(attendance_on, callback_data=f"tsearch:toggle:attendance:{chat_id}:1"),
                InlineKeyboardButton(attendance_off, callback_data=f"tsearch:toggle:attendance:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 附近搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(nearby_on, callback_data=f"tsearch:toggle:nearby:{chat_id}:1"),
                InlineKeyboardButton(nearby_off, callback_data=f"tsearch:toggle:nearby:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("🔘 底部按钮：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(f"🔖 {footer_label}", callback_data=f"tsearch:home:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🧹 删除消息：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton("✅ 删除" if setting.delete_mode != "none" else "❌ 不删除", callback_data=f"tsearch:delete_mode:{chat_id}:{'delete' if setting.delete_mode == 'none' else 'none'}"),
            ],
            [InlineKeyboardButton("📍 代录老师位置", callback_data=f"tsearch:delegate:start:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_attendance_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.garage_features_service import TeacherSearchService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            open_teachers = await TeacherSearchService.list_open_course_teachers(session, chat_id)
            await session.commit()

        force_on = "✅ 启动" if setting.force_location_enabled else "启动"
        force_off = "关闭" if setting.force_location_enabled else "✅ 关闭"
        open_count = f"{len(open_teachers)} 人"
        text = (
            "🔎 老师搜索 | 开课详情\n\n"
            f"开课打卡：{'✅ 启动' if setting.attendance_enabled else '❌ 关闭'}\n"
            f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}\n"
            f"开课老师：{open_count}\n\n"
            "说明：为了保持首页与文档布局一致，强制录入与开课老师查询收纳到本页。"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 强制录入：", callback_data=f"tsearch:attendance:menu:{chat_id}"),
                InlineKeyboardButton(force_on, callback_data=f"tsearch:toggle:force_loc:{chat_id}:1"),
                InlineKeyboardButton(force_off, callback_data=f"tsearch:toggle:force_loc:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("📚 开课老师", callback_data=f"tsearch:open_course:list:{chat_id}:0"),
                InlineKeyboardButton(open_count, callback_data=f"tsearch:open_course:list:{chat_id}:0"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_car_review_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.models.core import TgUser
        from bot.services.integration.garage_features_service import CarReviewService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await CarReviewService.get_setting(session, chat_id)
            fields = await CarReviewService.list_custom_fields(session, chat_id)
            reports = await CarReviewService.list_recent_reports(session, chat_id, limit=20)
            approver = await session.get(TgUser, setting.approver_user_id) if setting.approver_user_id else None
            await session.commit()

        mode_label = "默认" if setting.review_mode == "default" else "简易"
        lookup_label = {"exact": "精准", "contains": "包含", "off": "关闭"}.get(setting.teacher_lookup_mode, setting.teacher_lookup_mode)
        approver_label = f"@{approver.username}" if approver and approver.username else ("未指定" if not setting.approver_user_id else str(setting.approver_user_id))
        pending_count = sum(1 for item in reports if item.report_status == "pending")
        enabled_fields_count = sum(1 for item in fields if item.enabled)
        text = (
            "💯 车评系统\n\n"
            "群友可以对榜上的老师进行评价，审核通过可以自动发布，并给提交者奖励积分。\n\n"
            f"开关：{'✅ 启动' if setting.enabled else '❌ 关闭'}\n"
            f"模式：{mode_label}\n"
            f"查车评：{lookup_label}\n"
            f"提交评价指令：{setting.submit_command}\n"
            f"查询排行指令：{setting.rank_command}\n"
            f"报告发布：主群={'✅' if setting.publish_to_main_group else '❌'} / 评论区={'✅' if setting.publish_to_comment_group else '❌'} / 频道={'✅' if setting.publish_to_bound_channel else '❌'}\n"
            f"积分奖励：加 {setting.reward_points} 积分\n"
            f"审核人员：{approver_label}\n"
            f"自定义项：{enabled_fields_count}/{len(fields)} 项启用\n"
            f"最近报告：{len(reports)} 条（待审核 {pending_count} 条）"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 开关：", callback_data=f"crv:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.enabled else "启动", callback_data=f"crv:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if setting.enabled else "❌ 关闭", callback_data=f"crv:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 模式：", callback_data=f"crv:home:{chat_id}"),
                InlineKeyboardButton("✅ 默认" if setting.review_mode == "default" else "默认", callback_data=f"crv:mode:{chat_id}:default"),
                InlineKeyboardButton("✅ 简易" if setting.review_mode == "simple" else "简易", callback_data=f"crv:mode:{chat_id}:simple"),
            ],
            [
                InlineKeyboardButton("⚙️ 查车评：", callback_data=f"crv:home:{chat_id}"),
                InlineKeyboardButton("✅ 精准" if setting.teacher_lookup_mode == "exact" else "精准", callback_data=f"crv:lookup:{chat_id}:exact"),
                InlineKeyboardButton("✅ 包含" if setting.teacher_lookup_mode == "contains" else "包含", callback_data=f"crv:lookup:{chat_id}:contains"),
            ],
            [InlineKeyboardButton("✅ 关闭查车评" if setting.teacher_lookup_mode == "off" else "🚫 关闭查车评", callback_data=f"crv:lookup:{chat_id}:off")],
            [InlineKeyboardButton("💬 提交评价指令", callback_data=f"crv:submit_cmd:edit:{chat_id}")],
            [InlineKeyboardButton("🥇 查询排行指令", callback_data=f"crv:rank_cmd:edit:{chat_id}")],
            [InlineKeyboardButton("📤 报告发布", callback_data=f"crv:publish_target:{chat_id}:menu")],
            [InlineKeyboardButton(f"🪙 积分奖励：加 {setting.reward_points} 积分", callback_data=f"crv:reward:{chat_id}")],
            [InlineKeyboardButton(f"🕵️ 审核人员：{approver_label}", callback_data=f"crv:approver:set:{chat_id}")],
            [InlineKeyboardButton(f"✏️ 自定义项（{enabled_fields_count}/{len(fields)}）", callback_data=f"crv:fields:{chat_id}")],
            [InlineKeyboardButton("📝 报告模版", callback_data=f"crv:template:edit:{chat_id}")],
            [InlineKeyboardButton(f"📂 评价管理（待审核 {pending_count}）", callback_data=f"crv:reports:{chat_id}")],
            [InlineKeyboardButton("👩 在榜老师", callback_data=f"tsearch:open_course:list:{chat_id}:0")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_car_review_fields_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.garage_features_service import CarReviewService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            fields = await CarReviewService.list_custom_fields(session, chat_id)
            await session.commit()

        lines = [
            "💯 车评系统 | 自定义项",
            "",
            "当前为基础版字段清单，启停和排序能力已入库，但管理页仍未完全展开。",
            "",
        ]
        for item in fields:
            lines.append(f"{item.field_label}（键：{item.field_key}｜{'✅ 启用' if item.enabled else '❌ 关闭'}）")
        if not fields:
            lines.append("暂无自定义项")
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]),
        )

    async def _show_car_review_reports_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        status: str = "all",
    ) -> None:
        from bot.services.integration.garage_features_service import CarReviewService

        normalized_status = _normalize_car_review_report_status(status)
        selected_code = _car_review_report_status_code(normalized_status)
        status_items = [
            ("all", "📋 全部"),
            ("pending", "🟡 待审核"),
            ("approved", "✅ 已通过"),
            ("published", "📢 已发布"),
            ("rejected", "❌ 已驳回"),
        ]
        status_icon_map = {
            "pending": "🟡",
            "approved": "✅",
            "published": "📢",
            "rejected": "❌",
        }
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            reports = await CarReviewService.list_reports(session, chat_id, status=normalized_status, limit=10)
            counts = await CarReviewService.count_reports_by_status(session, chat_id)
            await session.commit()

        summary = (
            f"📊 全部 {counts.get('all', 0)}"
            f"｜🟡 待审核 {counts.get('pending', 0)}"
            f"｜✅ 已通过 {counts.get('approved', 0)}"
            f"｜📢 已发布 {counts.get('published', 0)}"
            f"｜❌ 已驳回 {counts.get('rejected', 0)}"
        )
        current_status_name = {
            "all": "全部",
            "pending": "待审核",
            "approved": "已通过",
            "published": "已发布",
            "rejected": "已驳回",
        }.get(normalized_status, "全部")
        lines = [
            "💯 车评系统 | 评价管理",
            "",
            f"当前筛选：{current_status_name}",
            summary,
            "",
        ]
        keyboard_rows: list[list[InlineKeyboardButton]] = []
        filter_row_1: list[InlineKeyboardButton] = []
        filter_row_2: list[InlineKeyboardButton] = []
        for idx, (item_status, item_title) in enumerate(status_items):
            code = _car_review_report_status_code(item_status)
            label = f"{item_title}({counts.get(item_status, 0)})"
            if item_status == normalized_status:
                label = f"✅ {label}"
            button = InlineKeyboardButton(label, callback_data=f"crv:reports:{chat_id}:{code}")
            if idx < 3:
                filter_row_1.append(button)
            else:
                filter_row_2.append(button)
        keyboard_rows.append(filter_row_1)
        keyboard_rows.append(filter_row_2)
        if reports:
            for report in reports:
                status_icon = status_icon_map.get(report.report_status, "📄")
                lines.extend(
                    [
                        f"报告#{report.report_id}｜老师 {report.teacher_user_id or '未识别'}",
                        f"状态：{report.report_status}｜提交人：{report.author_user_id or '未知'}",
                        "",
                    ]
                )
                keyboard_rows.append(
                    [
                        InlineKeyboardButton(
                            f"{status_icon} 报告#{report.report_id}｜老师 {report.teacher_user_id or '未识别'}",
                            callback_data=f"crv:report:{chat_id}:detail:{report.report_id}:{selected_code}",
                        )
                    ]
                )
        else:
            lines.append("0 条数据，第 1 页/共 1 页")
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")])
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    async def _show_car_review_report_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        report_id: int,
        *,
        status: str = "all",
    ) -> None:
        from bot.services.integration.garage_features_service import CarReviewService

        normalized_status = _normalize_car_review_report_status(status)
        status_code = _car_review_report_status_code(normalized_status)
        status_text_map = {
            "pending": "🟡 待审核",
            "approved": "✅ 已通过",
            "published": "📢 已发布",
            "rejected": "❌ 已驳回",
        }
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            report = await CarReviewService.get_report(session, chat_id, report_id)
            logs = await CarReviewService.list_audit_logs(session, chat_id=chat_id, report_id=report_id, limit=8)
            await session.commit()
        if report is None:
            await answer_callback_query_safely(update, "报告不存在", show_alert=True)
            await self._show_car_review_reports_menu(update, context, chat_id, status=normalized_status)
            return
        score_total = (report.scores or {}).get("total_score", "-")
        logs_lines = ["审核日志："]
        if not logs:
            logs_lines.append("- 暂无日志")
        else:
            for item in logs:
                timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
                logs_lines.append(f"- {timestamp}｜{item.action}｜操作人 {item.operator_user_id or '-'}")
        lines = [
            "💯 车评系统 | 报告详情",
            "",
            f"报告编号：{report.report_id}",
            f"老师用户：{report.teacher_user_id or '未识别'}",
            f"提交用户：{report.author_user_id or '未知'}",
            f"当前状态：{status_text_map.get(report.report_status, report.report_status)}",
            f"综合评分：{score_total}",
            f"评价内容：{(report.review_text or '无').strip()[:200]}",
            "",
            *logs_lines,
        ]
        keyboard_rows: list[list[InlineKeyboardButton]] = []
        if report.report_status == "pending":
            keyboard_rows.append(
                [
                    InlineKeyboardButton("✅ 审核通过", callback_data=f"crv:report:{chat_id}:approve:{report.report_id}:{status_code}"),
                    InlineKeyboardButton("❌ 驳回", callback_data=f"crv:report:{chat_id}:reject:{report.report_id}:{status_code}"),
                ]
            )
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"crv:reports:{chat_id}:{status_code}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_car_review_publish_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from bot.services.integration.garage_features_service import CarReviewService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await CarReviewService.get_setting(session, chat_id)
            await session.commit()

        text = (
            "💯 车评系统 | 报告发送类型\n\n"
            "带图发送：只发首图\n"
            "直接发到主群：审核通过后直接发到主群\n"
            "评论车库帖子：审核通过后发到车库评论区\n"
            "发送指定频道：审核通过后发到绑定频道\n\n"
            "支持多选（一份报告发送到多个地方）"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🖼️ 首图发送：基础版固定开启", callback_data=f"crv:home:{chat_id}"),
            ],
            [InlineKeyboardButton(("✅ " if setting.publish_to_main_group else "") + "直接发到主群", callback_data=f"crv:publish_target:{chat_id}:main")],
            [InlineKeyboardButton(("✅ " if setting.publish_to_comment_group else "") + "评论车库帖子", callback_data=f"crv:publish_target:{chat_id}:comment")],
            [InlineKeyboardButton(("✅ " if setting.publish_to_bound_channel else "") + "发送指定频道", callback_data=f"crv:publish_target:{chat_id}:channel")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _start_text_input_state(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        state_chat_id: int,
        state_type: str,
        payload: dict,
    ) -> None:
        from bot.services.state.state_service import clear_user_state, set_user_state

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await clear_user_state(session, chat_id=state_chat_id, user_id=user_id)
            await clear_user_state(session, chat_id=user_id, user_id=user_id)
            await set_user_state(
                session,
                chat_id=state_chat_id,
                user_id=user_id,
                state_type=state_type,
                state_data=payload,
            )
            await session.commit()

    async def _handle_permission_policy(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ControlPermissionPolicy

        value = callback_data.get(3)
        if value not in {item.value for item in ControlPermissionPolicy}:
            await answer_callback_query_safely(update, "无效权限策略", show_alert=True)
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            settings.control_permission_policy = value
            await session.commit()

        await self._show_control_permission_menu(update, context, chat_id)

    async def _handle_group_lock(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType, GroupLockDeleteNoticeMode

        op = callback_data.get(3)
        arg = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if op == "toggle":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if arg == "phrase":
                    settings.group_lock_phrase_enabled = not bool(settings.group_lock_phrase_enabled)
                elif arg == "schedule":
                    settings.group_lock_schedule_enabled = not bool(settings.group_lock_schedule_enabled)
                elif arg == "delete_notice":
                    current = getattr(settings, "group_lock_delete_notice_mode", GroupLockDeleteNoticeMode.keep.value)
                    settings.group_lock_delete_notice_mode = (
                        GroupLockDeleteNoticeMode.delete.value
                        if current != GroupLockDeleteNoticeMode.delete.value
                        else GroupLockDeleteNoticeMode.keep.value
                    )
                await session.commit()
            await self._show_group_lock_menu(update, context, chat_id)
            return

        if op == "set":
            value = callback_data.get_int_optional(5)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if arg == "phrase":
                    settings.group_lock_phrase_enabled = bool(value)
                elif arg == "schedule":
                    settings.group_lock_schedule_enabled = bool(value)
                else:
                    await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                    return
                await session.commit()
            await self._show_group_lock_menu(update, context, chat_id)
            return

        if op == "notice":
            from bot.models.enums import GroupLockDeleteNoticeMode

            mode = callback_data.get(4)
            if mode not in {GroupLockDeleteNoticeMode.delete.value, GroupLockDeleteNoticeMode.keep.value}:
                await answer_callback_query_safely(update, "无效通知策略", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.group_lock_delete_notice_mode = mode
                await session.commit()
            await self._show_group_lock_menu(update, context, chat_id)
            return

        if op == "input":
            state_map = {
                "open_phrase": ConversationStateType.group_lock_open_keyword_input.value,
                "close_phrase": ConversationStateType.group_lock_close_keyword_input.value,
                "open_time": ConversationStateType.group_lock_open_time_input.value,
                "close_time": ConversationStateType.group_lock_close_time_input.value,
            }
            state_type = state_map.get(arg)
            if state_type is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type,
                {"target_chat_id": chat_id},
            )
            prompt = {
                "open_phrase": "👉 请输入新的开群词：",
                "close_phrase": "👉 请输入新的关群词：",
                "open_time": "👉 请输入开群时间（格式 HH:MM）：",
                "close_time": "👉 请输入关群时间（格式 HH:MM）：",
            }[arg]
            await self.message_helper.safe_edit(update, prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:closegroup:{chat_id}")]]))

    async def _handle_rename_monitor(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType

        op = callback_data.get(3)
        arg = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if op == "toggle":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.name_change_monitor_enabled = not bool(getattr(settings, "name_change_monitor_enabled", False))
                await session.commit()
            await self._show_rename_monitor_menu(update, context, chat_id)
            return

        if op == "set" and arg == "enabled":
            value = callback_data.get_int_optional(5)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.name_change_monitor_enabled = bool(value)
                await session.commit()
            await self._show_rename_monitor_menu(update, context, chat_id)
            return

        if op == "input" and arg == "text":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                template_text = getattr(settings, "name_change_monitor_template_text", "") or (
                    "检测到用户{userId}修改{changeType}\n"
                    "原{changeType}: {oldContent}\n"
                    "新{changeType}: {newContent}\n\n"
                    "请注意规避风险"
                )
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.rename_monitor_text_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                (
                    "🕵️ 用户改名监控 | 修改文案\n\n"
                    f"当前文案：{template_text}\n\n"
                    "替换符\n"
                    "└ {changeType} = 改变的类型\n"
                    "└ {oldContent} = 改变前内容\n"
                    "└ {newContent} = 改变后内容\n"
                    "└ {userId} = 用户id\n\n"
                    "👉 现在输入新的文案内容："
                ),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:renamewatch:{chat_id}")]]),
            )
            return

        if op == "preview":
            preview = (
                "检测到用户123456修改昵称\n"
                "原昵称: 老名字\n"
                "新昵称: 新名字\n\n"
                "请注意规避风险"
            )
            await answer_callback_query_safely(update, "已生成预览", show_alert=False)
            await self.message_helper.safe_edit(
                update,
                preview,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:renamewatch:{chat_id}")]]),
            )
            return

        if op in {"delete_after", "cycle_delete_after"}:
            seconds = callback_data.get_int_optional(4)
            options = [15, 30, 60, 90]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "name_change_monitor_delete_after_seconds", 60) or 60)
                if seconds is None:
                    next_seconds = options[(options.index(current) + 1) % len(options)] if current in options else 60
                else:
                    next_seconds = seconds
                settings.name_change_monitor_delete_after_seconds = next_seconds
                await session.commit()
            await self._show_rename_monitor_menu(update, context, chat_id)

    async def _handle_force_subscribe(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType, ForceSubscribeAction

        op = callback_data.get(3)
        arg = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if op == "toggle":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if arg == "buttons":
                    settings.force_subscribe_custom_buttons_enabled = not bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
                else:
                    settings.force_subscribe_enabled = not bool(getattr(settings, "force_subscribe_enabled", False))
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "input":
            state_map = {
                "channel1": ConversationStateType.force_subscribe_channel_1_input.value,
                "channel2": ConversationStateType.force_subscribe_channel_2_input.value,
                "text": ConversationStateType.force_subscribe_text_input.value,
                "cover": ConversationStateType.force_subscribe_cover_input.value,
                "buttons": ConversationStateType.force_subscribe_buttons_input.value,
            }
            state_type = state_map.get(arg)
            if state_type is None:
                await answer_callback_query_safely(update, "暂未支持此项", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type,
                {"target_chat_id": chat_id},
            )
            prompt = {
                "channel1": "👉 请回复需要绑定的频道1（频道id、用户名或链接）：",
                "channel2": "👉 请回复需要绑定的频道2（频道id、用户名或链接）：",
                "text": "👉 现在输入新的文案内容：",
                "cover": "👉 请发送图片或视频文件；发送“清空”可移除封面。",
                "buttons": (
                    "👉 请输入按钮配置。\n"
                    "支持两种格式：\n"
                    "1) JSON：[[{\"text\":\"加入频道\",\"url\":\"https://t.me/example\"}]]\n"
                    "2) 文本行：每行一个按钮，格式“按钮文案|https://t.me/example”\n"
                    "发送“清空”可移除按钮。"
                ),
            }[arg]
            await self.message_helper.safe_edit(
                update,
                prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:forcesub:{chat_id}")]]),
            )
            return

        if op == "preview":
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                await session.commit()
            text = (
                "👀 强制订阅 | 预览效果\n\n"
                "这是用户未订阅时会收到的提示样式预览。"
            )
            reply_markup = _build_force_subscribe_preview_markup(settings, chat_id)
            await self.message_helper.safe_edit(update, text, reply_markup=reply_markup)
            return

        if op in {"delete_after", "cycle_delete_after"}:
            seconds = callback_data.get_int_optional(4)
            options = [15, 30, 60, 90, 120, 300]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "force_subscribe_delete_warn_after_seconds", 60) or 60)
                if seconds is None:
                    next_seconds = options[(options.index(current) + 1) % len(options)] if current in options else 60
                else:
                    next_seconds = seconds
                settings.force_subscribe_delete_warn_after_seconds = next_seconds
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "cycle_check_mode":
            options = ["all", "any"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = getattr(settings, "force_subscribe_check_mode", "all")
                next_mode = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
                settings.force_subscribe_check_mode = next_mode
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "cycle_action":
            options = [
                ForceSubscribeAction.delete_and_warn.value,
                ForceSubscribeAction.delete_only.value,
                ForceSubscribeAction.warn_only.value,
                ForceSubscribeAction.mute.value,
            ]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = getattr(
                    settings,
                    "force_subscribe_not_subscribed_action",
                    ForceSubscribeAction.delete_and_warn.value,
                )
                next_action = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
                settings.force_subscribe_not_subscribed_action = next_action
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "clear_cover":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.force_subscribe_cover_media_type = None
                settings.force_subscribe_cover_file_id = None
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

    async def _handle_welcome(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType, WelcomeDeleteMode, WelcomeMode
        from bot.services.welcome_service import WelcomeService

        op = callback_data.get(3)
        db: Database = context.application.bot_data["db"]

        if op == "add":
            async with db.session_factory() as session:
                item = await WelcomeService.create_message(session, chat_id)
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, item.id)
            return

        if op == "detail":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "toggle":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                item = await WelcomeService.get_message(session, chat_id, welcome_id)
                await WelcomeService.update_field(session, chat_id, welcome_id, enabled=not item.enabled)
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "mode":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                item = await WelcomeService.get_message(session, chat_id, welcome_id)
                next_mode = (
                    WelcomeMode.on_join.value
                    if item.welcome_mode == WelcomeMode.after_verify.value
                    else WelcomeMode.after_verify.value
                )
                await WelcomeService.update_field(session, chat_id, welcome_id, welcome_mode=next_mode)
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "delete":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                await WelcomeService.delete_message(session, chat_id, welcome_id)
                await session.commit()
            await self._show_welcome_list_menu(update, context, chat_id)
            return

        if op == "preview":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                await WelcomeService.preview(
                    context,
                    session,
                    preview_chat_id=update.effective_user.id,
                    chat_id=chat_id,
                    welcome_id=welcome_id,
                    member=update.effective_user,
                    user_id=update.effective_user.id,
                )
                await session.commit()
            await answer_callback_query_safely(update, "已发送预览到当前私聊", show_alert=False)
            return

        if op == "cycle_delete":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            options: list[tuple[str, int | None]] = [
                (WelcomeDeleteMode.seconds.value, 15),
                (WelcomeDeleteMode.seconds.value, 30),
                (WelcomeDeleteMode.seconds.value, 60),
                (WelcomeDeleteMode.seconds.value, 90),
                (WelcomeDeleteMode.seconds.value, 120),
                (WelcomeDeleteMode.seconds.value, 300),
                (WelcomeDeleteMode.delete_prev.value, None),
                (WelcomeDeleteMode.keep.value, None),
            ]
            async with db.session_factory() as session:
                item = await WelcomeService.get_message(session, chat_id, welcome_id)
                current = (item.delete_mode, item.delete_delay_seconds)
                try:
                    index = options.index(current)
                except ValueError:
                    index = -1
                next_mode, next_delay = options[(index + 1) % len(options)]
                await WelcomeService.update_field(
                    session,
                    chat_id,
                    welcome_id,
                    delete_mode=next_mode,
                    delete_delay_seconds=next_delay,
                )
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "input":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            field = callback_data.get(5)
            state_map = {
                "title": ConversationStateType.welcome_title_input.value,
                "text": ConversationStateType.welcome_text_input.value,
                "cover": ConversationStateType.welcome_cover_input.value,
                "buttons": ConversationStateType.welcome_buttons_input.value,
            }
            state_type = state_map.get(field)
            if state_type is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type,
                {"target_chat_id": chat_id, "welcome_id": welcome_id},
            )
            prompt = {
                "title": "👉 请输入标题备注：",
                "text": "👉 请输入欢迎文本，可使用 {member} {group} {userid} {nickname}：",
                "cover": "👉 请发送图片或视频；发送“清空”可移除封面。",
                "buttons": "👉 请输入按钮 JSON，例如 [[{\"text\":\"联系管理员\",\"url\":\"https://t.me/example\"}]]；发送“清空”可移除按钮。",
            }[field]
            await self.message_helper.safe_edit(
                update,
                prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:wel:{chat_id}:detail:{welcome_id}")]]),
            )

    async def _handle_alliance(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType
        from bot.services.integration.alliance_service import AllianceService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_alliance_menu(update, context, chat_id)
            return

        if action == "members":
            await self._show_alliance_members_menu(update, context, chat_id)
            return

        if action == "create" and callback_data.get(2) == "input":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.alliance_create_name_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🖐 联盟功能 | 创建联盟\n\n👉 请取一个联盟名称：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")]]),
            )
            return

        if action == "join" and callback_data.get(2) == "input":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.alliance_join_code_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🖐 联盟功能 | 加入联盟\n\n👉 请输入联盟邀请码：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")]]),
            )
            return

        if action == "jointban" and callback_data.get(2) == "toggle":
            enabled = callback_data.get_int_optional(4)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await AllianceService.set_joint_ban_enabled(
                    session,
                    chat_id=chat_id,
                    operator_user_id=update.effective_user.id,
                    enabled=bool(enabled),
                )
                await session.commit()
            await self._show_alliance_menu(update, context, chat_id)
            return

        if action == "invite" and callback_data.get(2) == "show":
            async with db.session_factory() as session:
                try:
                    invite_code = await AllianceService.rotate_invite_code(
                        session,
                        chat_id=chat_id,
                        operator_user_id=update.effective_user.id,
                    )
                    await session.commit()
                except ValidationError as exc:
                    await session.rollback()
                    await answer_callback_query_safely(update, str(exc), show_alert=True)
                    return
            await answer_callback_query_safely(update, f"新的联盟邀请码：{invite_code}", show_alert=True)
            return

        if action == "invite" and callback_data.get(2) == "denied":
            await answer_callback_query_safely(update, "只有创建群可以重置联盟邀请码。", show_alert=True)
            return

        if action == "leave" and callback_data.get(3) == "confirm":
            try:
                async with db.session_factory() as session:
                    await AllianceService.leave_alliance(
                        session,
                        chat_id=chat_id,
                        operator_user_id=update.effective_user.id,
                    )
                    await session.commit()
            except ValidationError as exc:
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            await self._show_alliance_menu(update, context, chat_id)
            return

        await self._show_alliance_menu(update, context, chat_id)

    async def _handle_garage_forward(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType
        from bot.services.integration.garage_forward_service import GarageForwardService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageForwardService.update_setting(session, chat_id, enabled=bool(enabled))
                await session.commit()
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "mode":
            mode = callback_data.get(3)
            if mode not in {"all", "text", "media", "keyword"}:
                await answer_callback_query_safely(update, "无效同步模式", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageForwardService.update_setting(session, chat_id, sync_mode=mode)
                await session.commit()
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "keywords" and callback_data.get(2) == "input":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_forward_keyword_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🔁 车库转发 | 关键词规则\n\n👉 请输入关键词，使用空格、逗号或换行分隔：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]),
            )
            return

        if action == "source" and callback_data.get(2) == "add":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_forward_source_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🔁 车库转发 | 添加来源频道\n\n👉 请输入来源频道 ID、用户名或邀请链接：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]),
            )
            return

        if action == "source" and callback_data.get(2) == "remove":
            source_id = callback_data.get_int_optional(4)
            if source_id is None:
                await answer_callback_query_safely(update, "无效来源频道", show_alert=True)
                return
            async with db.session_factory() as session:
                deleted = await GarageForwardService.remove_source(session, chat_id=chat_id, source_id=source_id)
                await session.commit()
            if not deleted:
                await answer_callback_query_safely(update, "来源频道不存在", show_alert=True)
                return
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "audit":
            result = _normalize_gfw_audit_result(callback_data.get(3) or "a")
            await self._show_garage_forward_audit_menu(update, context, chat_id, result=result)
            return

        await self._show_garage_forward_prompt(update, context, chat_id)

    async def _handle_garage_auth(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType
        from bot.services.integration.garage_features_service import GarageAuthService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_garage_auth_menu(update, context, chat_id)
            return
        if action == "toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageAuthService.update_settings(session, chat_id, garage_auth_enabled=bool(enabled))
                await session.commit()
            await self._show_garage_auth_menu(update, context, chat_id)
            return
        if action == "badge":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_badge_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🚗 车库认证 | 认证图标\n\n👉 请输入新的认证图标：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
            )
            return
        if action == "teacher":
            sub = callback_data.get(2)
            if sub == "list":
                await self._show_garage_teacher_list_menu(update, context, chat_id, callback_data.get_int_optional(4) or 0)
                return
            if sub == "add":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_teacher_input.value,
                    {"target_chat_id": chat_id},
                )
                await self.message_helper.safe_edit(
                    update,
                    "🚗 车库认证 | 手动添加认证老师\n\n👉 请输入用户名或ID：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:teacher:list:{chat_id}:0")]]),
                )
                return
            if sub == "del":
                user_id = callback_data.get_int_optional(4)
                if user_id is None:
                    await answer_callback_query_safely(update, "老师参数无效", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.remove_teacher(session, chat_id, user_id)
                    await session.commit()
                await self._show_garage_teacher_list_menu(update, context, chat_id, 0)
                return
        if action == "limit":
            sub = callback_data.get(2)
            if sub == "toggle":
                enabled = callback_data.get_int_optional(4)
                if enabled not in {0, 1}:
                    await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_limit_enabled=bool(enabled))
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub == "mode":
                mode = callback_data.get(4)
                if mode not in {"none", "image", "image_text"}:
                    await answer_callback_query_safely(update, "无效模式", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_limit_mode=mode)
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub in {"interval", "max"}:
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_limit_interval_input.value if sub == "interval" else ConversationStateType.garage_limit_max_count_input.value,
                    {"target_chat_id": chat_id},
                )
                prompt = "🚗 车库认证 | 时间间隔\n\n👉 请输入限制时间间隔（秒）："
                if sub == "max":
                    prompt = "🚗 车库认证 | 限制条数\n\n👉 请输入限制条数："
                await self.message_helper.safe_edit(
                    update,
                    prompt,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
                )
                return
        if action == "wl":
            sub = callback_data.get(2)
            if sub == "list":
                await self._show_garage_whitelist_menu(update, context, chat_id, callback_data.get_int_optional(4) or 0)
                return
            if sub == "add":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_whitelist_input.value,
                    {"target_chat_id": chat_id},
                )
                await self.message_helper.safe_edit(
                    update,
                    "📄 老师发言限制 | 添加白名单\n\n👉 请输入用户名或ID：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:wl:list:{chat_id}:0")]]),
                )
                return
            if sub == "del":
                user_id = callback_data.get_int_optional(4)
                if user_id is None:
                    await answer_callback_query_safely(update, "白名单参数无效", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.remove_whitelist(session, chat_id, user_id)
                    await session.commit()
                await self._show_garage_whitelist_menu(update, context, chat_id, 0)
                return
        if action == "summary":
            sub = callback_data.get(2)
            if sub == "partition":
                value = callback_data.get(4)
                if value not in {"region", "price"}:
                    await answer_callback_query_safely(update, "无效分区类型", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_summary_partition_by=value)
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub == "open":
                value = callback_data.get_int_optional(4)
                if value not in {0, 1}:
                    await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_summary_only_open_course=bool(value))
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub == "gen":
                async with db.session_factory() as session:
                    summary_text = await GarageAuthService.build_teacher_summary(session, chat_id)
                    await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    summary_text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
                )
                return
        await self._show_garage_auth_menu(update, context, chat_id)

    async def _handle_teacher_search(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType
        from bot.services.integration.garage_features_service import TeacherSearchService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "attendance" and callback_data.get(2) == "menu":
            await self._show_teacher_search_attendance_menu(update, context, chat_id)
            return
        if action == "toggle":
            field = callback_data.get(2)
            value = callback_data.get_int_optional(4)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            field_map = {
                "tag": "tag_search_enabled",
                "nearby": "nearby_search_enabled",
                "attendance": "attendance_enabled",
                "force_loc": "force_location_enabled",
            }
            setting_field = field_map.get(field)
            if setting_field is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, **{setting_field: bool(value)})
                await session.commit()
            if field == "force_loc":
                await self._show_teacher_search_attendance_menu(update, context, chat_id)
            else:
                await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "delete_mode":
            mode = callback_data.get(3)
            if mode not in {"none", "delete"}:
                await answer_callback_query_safely(update, "无效删除策略", show_alert=True)
                return
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, delete_mode=mode)
                await session.commit()
            await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "delegate" and callback_data.get(2) == "start":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.teacher_search_delegate_target_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "📍 代替老师录入位置\n\n👉 请输入上牌老师的用户名或ID：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")]]),
            )
            return
        if action == "open_course" and callback_data.get(2) == "list":
            page = callback_data.get_int_optional(4) or 0
            async with db.session_factory() as session:
                rows = await TeacherSearchService.list_open_course_teachers(session, chat_id)
                await session.commit()
            lines = ["🔎 老师搜索 | 开课老师", ""]
            if not rows:
                lines.append("暂无开课老师")
            else:
                for item, user in rows[page * 10: page * 10 + 10]:
                    name = f"@{user.username}" if user and user.username else str(item.user_id)
                    lines.append(f"- {name}")
            await self.message_helper.safe_edit(
                update,
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")]]),
            )
            return
        await self._show_teacher_search_menu(update, context, chat_id)

    async def _handle_car_review(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from bot.models.enums import ConversationStateType
        from bot.services.integration.garage_features_service import CarReviewService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await CarReviewService.update_setting(session, chat_id, enabled=bool(enabled))
                await session.commit()
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "mode":
            mode = callback_data.get(3)
            if mode not in {"default", "simple"}:
                await answer_callback_query_safely(update, "无效模式", show_alert=True)
                return
            async with db.session_factory() as session:
                await CarReviewService.update_setting(session, chat_id, review_mode=mode)
                await session.commit()
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "lookup":
            mode = callback_data.get(3)
            if mode not in {"exact", "contains", "off"}:
                await answer_callback_query_safely(update, "无效查找模式", show_alert=True)
                return
            async with db.session_factory() as session:
                await CarReviewService.update_setting(session, chat_id, teacher_lookup_mode=mode)
                await session.commit()
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "submit_cmd" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_submit_command_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 提交报告指令\n\n👉 请输入新的指令：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "rank_cmd" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_rank_command_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 查询排行指令\n\n👉 请输入新的指令：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "publish_target":
            target = callback_data.get(3)
            if target == "menu":
                await self._show_car_review_publish_menu(update, context, chat_id)
                return
            field_map = {
                "main": "publish_to_main_group",
                "comment": "publish_to_comment_group",
                "channel": "publish_to_bound_channel",
            }
            setting_field = field_map.get(target)
            if setting_field is None:
                await answer_callback_query_safely(update, "无效发布目标", show_alert=True)
                return
            async with db.session_factory() as session:
                setting = await CarReviewService.get_setting(session, chat_id)
                await CarReviewService.update_setting(session, chat_id, **{setting_field: not bool(getattr(setting, setting_field))})
                await session.commit()
            await self._show_car_review_publish_menu(update, context, chat_id)
            return
        if action == "approver" and callback_data.get(2) == "set":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_approver_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 指定审核人\n\n👉 请输入用户名或ID，发送“清空”取消：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "template" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_template_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 评价模板\n\n👉 请输入新的模板：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "reward":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_reward_points_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 积分奖励\n\n👉 请输入奖励积分：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "fields":
            await self._show_car_review_fields_menu(update, context, chat_id)
            return
        if action == "reports":
            status = _normalize_car_review_report_status(callback_data.get(3) or "0")
            await self._show_car_review_reports_menu(update, context, chat_id, status=status)
            return
        if action == "report":
            sub = callback_data.get(3)
            report_id = callback_data.get_int_optional(4)
            status = _normalize_car_review_report_status(callback_data.get(5) or "0")
            if report_id is None:
                await answer_callback_query_safely(update, "报告参数无效", show_alert=True)
                await self._show_car_review_reports_menu(update, context, chat_id, status=status)
                return
            if sub == "detail":
                await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
                return
            async with db.session_factory() as session:
                if sub == "approve":
                    report = await CarReviewService.approve_report(
                        session,
                        chat_id=chat_id,
                        report_id=report_id,
                        approver_user_id=update.effective_user.id,
                    )
                    message = "报告已通过审核" if report is not None else "报告不存在"
                elif sub == "reject":
                    report = await CarReviewService.reject_report(
                        session,
                        chat_id=chat_id,
                        report_id=report_id,
                        operator_user_id=update.effective_user.id,
                        reason="管理员驳回",
                    )
                    message = "报告已驳回" if report is not None else "报告不存在"
                else:
                    await session.commit()
                    await answer_callback_query_safely(update, "暂不支持该审核操作", show_alert=True)
                    await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
                    return
                await session.commit()
            await answer_callback_query_safely(update, message, show_alert=False)
            await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
            return
        await self._show_car_review_menu(update, context, chat_id)

    async def _handle_verification_config_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """开始验证配置流程"""
        from bot.models.enums import ConversationStateType
        from bot.services.state.state_service import clear_user_state, set_user_state

        if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
            return
        q = update.callback_query
        await q.answer()

        chat = update.effective_chat
        user = update.effective_user

        log.warning(
            "=== VERIFICATION_CONFIG_START CALLED ===",
            target_chat_id=target_chat_id,
            user_id=user.id,
            chat_type=chat.type,
        )

        try:
            db: Database = context.application.bot_data["db"]

            # 确保目标群组存在
            from bot.models.core import TgChat
            from sqlalchemy import select

            target_chat_title = None
            async with db.session_factory() as session:
                await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title or f"群组{target_chat_id}")

                # 获取群组信息
                chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
                chat_result = await session.execute(chat_stmt)
                target_chat_obj = chat_result.scalar_one_or_none()
                target_chat_title = target_chat_obj.title if target_chat_obj else f"群组{target_chat_id}"

                # 私聊模式下，确保私聊 chat 记录存在
                if chat.type == "private":
                    await ensure_chat(session, chat_id=user.id, chat_type="private", title=chat.title)

                await ensure_user(
                    session,
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    language_code=user.language_code,
                )

                # 统一使用目标群组 ID 保存状态
                state_chat_id = target_chat_id

                # 清除所有旧状态（包括私聊状态和群组状态）
                await clear_user_state(session, chat_id=state_chat_id, user_id=user.id)  # 清除群组状态
                await clear_user_state(session, chat_id=user.id, user_id=user.id)  # 清除私聊状态

                # 【修复】清除该用户的所有旧的 verification_config 状态（避免多行问题）
                from bot.models.core import ConversationState
                from sqlalchemy import delete
                await session.execute(
                    delete(ConversationState).where(
                        ConversationState.user_id == user.id,
                        ConversationState.state_type == ConversationStateType.verification_config.value,
                    )
                )

                # 设置当前管理的群组（必须在清除状态之后设置，否则会被清除）
                # 【修复】将 _set_current_chat 移到 clear_user_state 之后，避免 managed_chat_id 被清除
                await self._set_current_chat(db, user.id, target_chat_id)

                await set_user_state(
                    session,
                    chat_id=state_chat_id,
                    user_id=user.id,
                    state_type=ConversationStateType.verification_config.value,
                    state_data={"step": "config", "target_chat_id": target_chat_id},
                )

                await session.commit()

                log.warning(
                    "=== VERIFICATION_CONFIG_STATE_SET ===",
                    state_chat_id=state_chat_id,
                    user_id=user.id,
                    state_type=ConversationStateType.verification_config.value,
                )

        except Exception as e:
            log.exception("verification_config_start_error", error=str(e))
            await q.edit_message_text(f"❌ 启动失败: {str(e)}")
            return

        # 显示配置说明
        text = "🤖 验证功能配置 ( /cancel 取消)\n\n"
        text += "请按以下格式发送配置：\n\n"
        text += "```\n"
        text += "状态:开启\n"
        text += "验证方式:管理员确认\n"
        text += "超时时间:180\n"
        text += "超时处理:禁言\n"
        text += "禁言时长:86400\n"
        text += "限制发言:是\n"
        text += "```\n\n"
        text += "📋 配置说明：\n"
        text += "• 状态: 开启/关闭\n"
        text += "• 验证方式: 按钮验证/数学题/验证码/管理员确认\n"
        text += "• 超时时间: 秒数（如 180=3分钟，管理员确认模式不生效）\n"
        text += "• 超时处理: 禁言/踢出\n"
        text += "• 禁言时长: 秒数（默认 86400=1天）\n"
        text += "• 限制发言: 是/否（验证期间是否限制发送消息）"

        # 添加取消按钮
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ 取消配置", callback_data=f"verification:cancel:{target_chat_id}")]
        ])

        try:
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            await q.edit_message_text(text.replace("```", ""), reply_markup=keyboard)

    async def _show_verification_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示新人验证设置菜单"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        log.warning(
            "=== _SHOW_VERIFICATION_MENU CALLED ===",
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        mode_label = {
            "button": "按钮验证",
            "math": "数学题",
            "captcha": "验证码",
            "admin": "管理员确认",
        }.get(settings.verification_mode, settings.verification_mode)
        status_label = "✅ 开启" if settings.verification_enabled else "❌ 关闭"
        spam_label = "✅ 开启" if bool(getattr(settings, "join_spam_guard_enabled", False)) else "❌ 关闭"
        review_label = "✅ 开启" if bool(getattr(settings, "join_self_review_enabled", False)) else "❌ 关闭"
        burst_label = "✅ 开启" if bool(getattr(settings, "join_burst_enabled", False)) else "❌ 关闭"

        text = (
            f"🛡️ [{chat_title}] 进群验证\n\n"
            f"进群验证：{status_label}｜当前方式：{mode_label}\n"
            f"垃圾拦截：{spam_label}\n"
            f"进群自助审核：{review_label}\n"
            f"禁止批量进群：{burst_label}\n\n"
            "当前已接通基础验证链路与三个辅助子页配置；执行侧仍会继续向完整 join guard 流水线补齐。"
        )

        buttons = [
            [InlineKeyboardButton("🛡️ 进群验证", callback_data=f"adm:vfy_config:{chat_id}")],
            [InlineKeyboardButton("🚯 垃圾拦截", callback_data=f"adm:vfy_home:{chat_id}:spam")],
            [InlineKeyboardButton("📝 进群自助审核", callback_data=f"adm:vfy_home:{chat_id}:self_review")],
            [InlineKeyboardButton("🚪 禁止批量进群", callback_data=f"adm:vfy_home:{chat_id}:burst")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        log.info("=== CALLING SAFE_EDIT FOR VERIFICATION MENU ===")
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
        log.info("=== SAFE_EDIT COMPLETED ===")

    async def _show_join_spam_guard_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        lines = [
            "🚯 进群验证 | 垃圾拦截",
            "",
            f"📌 状态：{'✅ 开启' if settings.join_spam_guard_enabled else '❌ 关闭'}",
            f"🧪 命中阈值：{settings.join_spam_detect_rules_count} 条",
            f"💬 提示消息：{'✅ 开启' if settings.join_spam_send_invalid_msg_enabled else '❌ 关闭'}",
            f"🔇 禁言新人：{'✅ 开启' if settings.join_spam_mute_member_enabled else '❌ 关闭'}",
            f"👢 踢出新人：{'✅ 开启' if settings.join_spam_kick_member_enabled else '❌ 关闭'}",
            f"⏱️ 提示删除：{settings.join_spam_tip_delete_after_seconds} 秒",
        ]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 状态" if settings.join_spam_guard_enabled else "❌ 状态", callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:enabled"),
                InlineKeyboardButton(f"🧪 阈值 {settings.join_spam_detect_rules_count}", callback_data=f"adm:vfy_home:{chat_id}:spam:cycle:rules"),
            ],
            [
                InlineKeyboardButton(("💬 提示 ✅" if settings.join_spam_send_invalid_msg_enabled else "💬 提示 ❌"), callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:notify"),
                InlineKeyboardButton(("🔇 禁言 ✅" if settings.join_spam_mute_member_enabled else "🔇 禁言 ❌"), callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:mute"),
            ],
            [
                InlineKeyboardButton(("👢 踢出 ✅" if settings.join_spam_kick_member_enabled else "👢 踢出 ❌"), callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:kick"),
                InlineKeyboardButton(f"⏱️ 删除 {settings.join_spam_tip_delete_after_seconds}s", callback_data=f"adm:vfy_home:{chat_id}:spam:cycle:tip_sec"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_join_self_review_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        timeout_action_label = JOIN_SELF_REVIEW_ACTION_LABELS.get(
            settings.join_self_review_timeout_action,
            settings.join_self_review_timeout_action,
        )
        wrong_action_label = JOIN_SELF_REVIEW_ACTION_LABELS.get(
            settings.join_self_review_wrong_action,
            settings.join_self_review_wrong_action,
        )
        lines = [
            "📝 进群验证 | 自助审核",
            "",
            f"📌 状态：{'✅ 开启' if settings.join_self_review_enabled else '❌ 关闭'}",
            f"⏱️ 超时：{settings.join_self_review_timeout_seconds} 秒",
            f"⌛ 超时策略：{timeout_action_label}",
            f"❓ 答错策略：{wrong_action_label}",
        ]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 状态" if settings.join_self_review_enabled else "❌ 状态", callback_data=f"adm:vfy_home:{chat_id}:self_review:toggle:enabled"),
                InlineKeyboardButton(f"⏱️ 超时 {settings.join_self_review_timeout_seconds}s", callback_data=f"adm:vfy_home:{chat_id}:self_review:cycle:timeout"),
            ],
            [
                InlineKeyboardButton(timeout_action_label, callback_data=f"adm:vfy_home:{chat_id}:self_review:cycle:timeout_action"),
            ],
            [
                InlineKeyboardButton(wrong_action_label, callback_data=f"adm:vfy_home:{chat_id}:self_review:cycle:wrong_action"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_join_burst_guard_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        tip_mode_label = JOIN_BURST_TIP_MODE_LABELS.get(settings.join_burst_tip_mode, settings.join_burst_tip_mode)
        lines = [
            "🚪 进群验证 | 禁止批量进群",
            "",
            f"📌 状态：{'✅ 开启' if settings.join_burst_enabled else '❌ 关闭'}",
            f"🪟 时间窗口：{settings.join_burst_window_seconds} 秒",
            f"👥 触发人数：{settings.join_burst_threshold_count} 人",
            f"🔇 禁言：{'✅ 开启' if settings.join_burst_mute_enabled else '❌ 关闭'}",
            f"👢 踢出：{'✅ 开启' if settings.join_burst_kick_enabled else '❌ 关闭'}",
            f"💬 提示策略：{tip_mode_label}",
        ]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 状态" if settings.join_burst_enabled else "❌ 状态", callback_data=f"adm:vfy_home:{chat_id}:burst:toggle:enabled"),
                InlineKeyboardButton(f"🪟 窗口 {settings.join_burst_window_seconds}s", callback_data=f"adm:vfy_home:{chat_id}:burst:cycle:window"),
            ],
            [
                InlineKeyboardButton(f"👥 阈值 {settings.join_burst_threshold_count}", callback_data=f"adm:vfy_home:{chat_id}:burst:cycle:threshold"),
                InlineKeyboardButton(("🔇 禁言 ✅" if settings.join_burst_mute_enabled else "🔇 禁言 ❌"), callback_data=f"adm:vfy_home:{chat_id}:burst:toggle:mute"),
            ],
            [
                InlineKeyboardButton(("👢 踢出 ✅" if settings.join_burst_kick_enabled else "👢 踢出 ❌"), callback_data=f"adm:vfy_home:{chat_id}:burst:toggle:kick"),
                InlineKeyboardButton(tip_mode_label, callback_data=f"adm:vfy_home:{chat_id}:burst:cycle:tip_mode"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _handle_verification_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        section = callback_data.get(3)
        action = callback_data.get(4)
        key = callback_data.get(5)
        db: Database = context.application.bot_data["db"]

        if section == "spam":
            if action in {"", "home"}:
                await self._show_join_spam_guard_menu(update, context, chat_id)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if action == "toggle":
                    field_map = {
                        "enabled": "join_spam_guard_enabled",
                        "notify": "join_spam_send_invalid_msg_enabled",
                        "mute": "join_spam_mute_member_enabled",
                        "kick": "join_spam_kick_member_enabled",
                    }
                    field = field_map.get(key)
                    if field:
                        setattr(settings, field, not bool(getattr(settings, field)))
                elif action == "cycle":
                    if key == "rules":
                        settings.join_spam_detect_rules_count = _cycle_config_value(
                            settings.join_spam_detect_rules_count,
                            JOIN_SPAM_RULE_VALUES,
                        )
                    elif key == "tip_sec":
                        settings.join_spam_tip_delete_after_seconds = _cycle_config_value(
                            settings.join_spam_tip_delete_after_seconds,
                            JOIN_SPAM_TIP_DELETE_VALUES,
                        )
                await session.commit()
            await self._show_join_spam_guard_menu(update, context, chat_id)
            return

        if section == "self_review":
            if action in {"", "home"}:
                await self._show_join_self_review_menu(update, context, chat_id)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if action == "toggle" and key == "enabled":
                    settings.join_self_review_enabled = not bool(settings.join_self_review_enabled)
                elif action == "cycle":
                    if key == "timeout":
                        settings.join_self_review_timeout_seconds = _cycle_config_value(
                            settings.join_self_review_timeout_seconds,
                            JOIN_SELF_REVIEW_TIMEOUT_VALUES,
                        )
                    elif key == "timeout_action":
                        settings.join_self_review_timeout_action = _cycle_config_value(
                            settings.join_self_review_timeout_action,
                            list(JOIN_SELF_REVIEW_ACTION_LABELS.keys()),
                        )
                    elif key == "wrong_action":
                        settings.join_self_review_wrong_action = _cycle_config_value(
                            settings.join_self_review_wrong_action,
                            list(JOIN_SELF_REVIEW_ACTION_LABELS.keys()),
                        )
                await session.commit()
            await self._show_join_self_review_menu(update, context, chat_id)
            return

        if section == "burst":
            if action in {"", "home"}:
                await self._show_join_burst_guard_menu(update, context, chat_id)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if action == "toggle":
                    field_map = {
                        "enabled": "join_burst_enabled",
                        "mute": "join_burst_mute_enabled",
                        "kick": "join_burst_kick_enabled",
                    }
                    field = field_map.get(key)
                    if field:
                        setattr(settings, field, not bool(getattr(settings, field)))
                elif action == "cycle":
                    if key == "window":
                        settings.join_burst_window_seconds = _cycle_config_value(
                            settings.join_burst_window_seconds,
                            JOIN_BURST_WINDOW_VALUES,
                        )
                    elif key == "threshold":
                        settings.join_burst_threshold_count = _cycle_config_value(
                            settings.join_burst_threshold_count,
                            JOIN_BURST_THRESHOLD_VALUES,
                        )
                    elif key == "tip_mode":
                        settings.join_burst_tip_mode = _cycle_config_value(
                            settings.join_burst_tip_mode,
                            list(JOIN_BURST_TIP_MODE_LABELS.keys()),
                        )
                await session.commit()
            await self._show_join_burst_guard_menu(update, context, chat_id)
            return

        await self._show_verification_menu(update, context, chat_id)

    async def _show_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分设置菜单"""
        from bot.keyboards.admin.points import points_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        all_enabled = bool(settings.sign_enabled or settings.message_points_enabled or settings.invite_points_enabled)
        text = (
            f"💰 [{chat_title}] 主积分（基础版）\n\n"
            f"状态：{'✅ 启动' if all_enabled else '❌ 关闭'}\n"
            f"签到：{'✅ 启动' if settings.sign_enabled else '❌ 关闭'}｜{settings.sign_points}分\n"
            f"发言：{'✅ 启动' if settings.message_points_enabled else '❌ 关闭'}｜{settings.message_points}分\n"
            f"邀请：{'✅ 启动' if settings.invite_points_enabled else '❌ 关闭'}｜{settings.invite_points}分\n\n"
            "当前先提供基础版积分中心，转让、日志导出、清空积分等仍按待实现入口收口。"
        )

        keyboard = points_config_keyboard(settings, chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_custom_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示自定义积分列表页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            items = await PointsExtendedService.list_custom_point_types(session, chat_id)
            await session.commit()

        lines = [
            "🌐 自定义积分",
            "",
            "可以创建多种积分类型，但是此积分只能通过管理员进行加减，使用场景：诚心分、贡献值等！",
            "",
        ]
        if items:
            for item in items:
                lines.extend(
                    [
                        f"{item.name}（状态：{'✅ 启用' if item.enabled else '❌ 关闭'}）",
                        f"└编号：{item.type_no}",
                        "",
                    ]
                )
            lines.append(f"{len(items)} 条数据，第 1 页/共 1 页")
        else:
            lines.append("0 条数据，第 1 页/共 1 页")

        await self.message_helper.safe_edit(
            update,
            text="\n".join(lines),
            reply_markup=custom_points_list_keyboard(items, chat_id),
        )

    async def _show_custom_points_add_placeholder(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """兼容旧入口：添加后进入详情页。"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await PointsExtendedService.create_custom_point_type(session, chat_id, update.effective_user.id)
            await session.commit()
        await self._show_custom_point_detail(update, context, chat_id, item.id)

    async def _show_points_level_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分等级列表页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_level_setting(session, chat_id)
            levels = await PointsExtendedService.list_levels(session, chat_id)
            await session.commit()

        level_lines = []
        if levels:
            for level in levels:
                perms = [
                    f"文字{'✅' if level.allow_text else '❌'}",
                    f"音频{'✅' if level.allow_audio else '❌'}",
                    f"图片{'✅' if level.allow_photo else '❌'}",
                    f"视频{'✅' if level.allow_video else '❌'}",
                    f"贴纸{'✅' if level.allow_sticker else '❌'}",
                    f"文件{'✅' if level.allow_document else '❌'}",
                    f"提到{'✅' if level.allow_mention else '❌'}",
                ]
                level_lines.extend([f"{level.level_name}（积分门槛线 > {level.point_threshold}）", "└" + " ".join(perms), ""])
        else:
            level_lines.append("待配置（积分门槛线 > 0）")
            level_lines.append("")
        total_pages = 1
        text = "\n".join(
            [
                "👨‍💻 积分等级",
                "",
                "通过主积分数量划分用户等级，并设置不同等级的权限",
                "",
                *level_lines,
                f"{len(levels)} 条数据，第 1 页/共 {total_pages} 页",
            ]
        )

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_level_list_keyboard(setting, levels, chat_id),
        )

    async def _show_points_level_add_placeholder(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """兼容旧入口：创建等级并进入详情页。"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            level = await PointsExtendedService.create_level(session, chat_id)
            await session.commit()
        await self._show_points_level_detail(update, context, chat_id, level.id)

    async def _show_points_mall_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城主配置页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await session.commit()
        text = "\n".join(
            [
                "🏦 积分商城",
                "",
                "用户可以使用积分兑换商品，增加积分价值，促进群活跃。",
                "",
                f"指令：群里输入 {setting.entry_command} 唤起商品列表",
            ]
        )

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_home_keyboard(setting, chat_id),
        )

    async def _show_points_mall_cover_placeholder(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城封面页"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await session.commit()
        text = (
            "🛍️ 积分商城 | 商城封面\n\n"
            f"当前封面：{'未设置' if not setting.cover_file_id else '已设置'}"
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_cover_keyboard(chat_id),
        )

    async def _show_points_mall_command_placeholder(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城修改指令页"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await set_user_state(
                session,
                chat_id=update.effective_user.id,
                user_id=update.effective_user.id,
                state_type="points_mall_command_input",
                state_data={"target_chat_id": chat_id},
            )
            await session.commit()
        text = (
            "⚙️ 积分商城 | 修改指令\n\n"
            f"当前指令：{setting.entry_command}\n\n"
            "👉 现在输入新的指令："
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_command_keyboard(chat_id),
        )

    async def _show_points_mall_products_placeholder(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城商品管理页"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            products = await PointsExtendedService.list_products(session, chat_id)
            await session.commit()
        if products:
            chunks: list[str] = ["🛍️ 管理商品 | 商品列表", ""]
            for product in products:
                chunks.extend(
                    [
                        f"商品名称：{product.name}",
                        f"顺序编号：{product.product_id}（排序权重{product.sort_weight}）",
                        f"兑换价格：{product.price_points}",
                        f"可售数量：{product.stock_left}/{product.stock_total}",
                        f"上架状态：{'✅' if product.status == 'on_sale' else '❌'}",
                        "",
                    ]
                )
            chunks.append(f"{len(products)} 条数据，第 1 页/共 1 页")
            text = "\n".join(chunks)
        else:
            text = "🛍️ 管理商品 | 商品列表\n\n0 条数据，第 1 页/共 1 页"
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_products_keyboard(products, chat_id),
        )

    async def _show_points_mall_orders_placeholder(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        product_id: int | None = None,
        status: str = "all",
    ) -> None:
        """显示积分商城订单管理页"""
        normalized_status = status if status in {"all", "created", "fulfilled", "canceled", "refunded"} else "all"
        status_name_map = {
            "all": "全部",
            "created": "待处理",
            "fulfilled": "已发放",
            "canceled": "已取消",
            "refunded": "已退款",
        }
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            orders = await PointsExtendedService.list_recent_orders(
                session,
                chat_id,
                limit=20,
                product_id=product_id,
                order_status=normalized_status,
            )
            status_counts = await PointsExtendedService.count_orders_by_status(
                session,
                chat_id=chat_id,
                product_id=product_id,
            )
            await session.commit()
        summary = (
            f"📊 全部 {status_counts.get('all', 0)}"
            f"｜🟡 待处理 {status_counts.get('created', 0)}"
            f"｜✅ 已发放 {status_counts.get('fulfilled', 0)}"
            f"｜❌ 已取消 {status_counts.get('canceled', 0)}"
            f"｜💸 已退款 {status_counts.get('refunded', 0)}"
        )
        if orders:
            title = "🧾 管理订单" if product_id is None else f"🧾 管理订单 | 商品 {product_id}"
            lines = [title, f"当前筛选：{status_name_map.get(normalized_status, '全部')}", summary, ""]
            for order in orders:
                lines.extend(
                    [
                        f"订单#{order.order_id}｜商品 {order.product_id}",
                        f"用户：{order.buyer_user_id}",
                        f"积分：{order.price_points}｜数量：{order.quantity}",
                        f"状态：{order.order_status}",
                        "",
                    ]
                )
            lines.append(f"{len(orders)} 条数据，第 1 页/共 1 页")
            text = "\n".join(lines)
        else:
            text = (
                f"🧾 管理订单\n当前筛选：{status_name_map.get(normalized_status, '全部')}\n{summary}\n\n0 条数据，第 1 页/共 1 页"
                if product_id is None
                else f"🧾 管理订单 | 商品 {product_id}\n当前筛选：{status_name_map.get(normalized_status, '全部')}\n{summary}\n\n0 条数据，第 1 页/共 1 页"
            )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_orders_keyboard(
                chat_id,
                orders=orders,
                product_id=product_id,
                status=normalized_status,
                status_counts=status_counts,
            ),
        )

    async def _show_auction_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await get_auction_setting(session, chat_id)
            auctions = await list_recent_auctions(session, chat_id, limit=5)
            await session.commit()
        chat_title = await self._get_chat_title(db, chat_id)
        lines = [format_auction_settings_text(chat_title, setting), "", "📋 最近拍卖："]
        if auctions:
            for item in auctions:
                lines.append(f"#{item.id} {item.title or '未命名'}｜{item.status}｜当前价 {item.current_price}")
        else:
            lines.append("暂无拍卖记录")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"auc:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.enabled else "启动", callback_data=f"auc:toggle:{chat_id}:enabled:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.enabled else "关闭", callback_data=f"auc:toggle:{chat_id}:enabled:0"),
            ],
            [
                InlineKeyboardButton("📌 消息置顶：", callback_data=f"auc:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.pin_message_enabled else "启动", callback_data=f"auc:toggle:{chat_id}:pin:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.pin_message_enabled else "关闭", callback_data=f"auc:toggle:{chat_id}:pin:0"),
            ],
            [
                InlineKeyboardButton("⏱ 自动延时：", callback_data=f"auc:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.auto_extend_enabled else "启动", callback_data=f"auc:toggle:{chat_id}:auto_extend:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.auto_extend_enabled else "关闭", callback_data=f"auc:toggle:{chat_id}:auto_extend:0"),
            ],
            [
                InlineKeyboardButton("👮 仅管理员" + (" ✅" if setting.create_permission == "admin" else ""), callback_data=f"auc:perm:{chat_id}:admin"),
                InlineKeyboardButton("👥 所有人" + (" ✅" if setting.create_permission == "all" else ""), callback_data=f"auc:perm:{chat_id}:all"),
            ],
            [
                InlineKeyboardButton("🚫 不关联" + (" ✅" if setting.points_mode == "none" else ""), callback_data=f"auc:points_mode:{chat_id}:none"),
                InlineKeyboardButton("🌑 主积分" + (" ✅" if setting.points_mode == "group_points" else ""), callback_data=f"auc:points_mode:{chat_id}:group_points"),
            ],
            [InlineKeyboardButton("📋 活动列表", callback_data=f"auc:list:{chat_id}:0")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_auction_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        page: int = 0,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            items, total_count = await list_auctions(session, chat_id, page=page, page_size=10)
            await session.commit()
        total_pages = max(1, (total_count + 9) // 10)
        current_page = min(max(page, 0), total_pages - 1)
        lines = [
            "💰 拍卖 | 活动列表",
            "",
            f"{total_count} 条数据，第 {current_page + 1} 页/共 {total_pages} 页",
            "",
        ]
        if items:
            for item in items:
                lines.extend(
                    [
                        f"#{item.id} {item.title or '未命名拍卖'}",
                        f"状态：{item.status}｜当前价：{item.current_price}",
                        "",
                    ]
                )
        else:
            lines.append("暂无拍卖记录")

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        for item in items:
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"📄 #{item.id} {item.title or '未命名拍卖'}"[:48],
                    callback_data=f"auc:detail:{chat_id}:{item.id}",
                )
            ])
        nav_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"auc:list:{chat_id}:{current_page - 1}"))
        if current_page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"auc:list:{chat_id}:{current_page + 1}"))
        if nav_row:
            keyboard_rows.append(nav_row)
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"auc:home:{chat_id}")])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_auction_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        auction_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await get_auction(session, chat_id, auction_id)
            await session.commit()
        if item is None:
            await self.message_helper.safe_edit(
                update,
                text="❌ 拍卖不存在",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回列表", callback_data=f"auc:list:{chat_id}:0")]]),
            )
            return
        text = "\n".join(
            [
                f"💰 拍卖详情 #{item.id}",
                "",
                f"标题：{item.title or '未命名拍卖'}",
                f"状态：{item.status}",
                f"起拍价：{item.start_price}",
                f"当前价：{item.current_price}",
                f"创建时间：{item.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
                f"截止时间：{item.end_at.astimezone().strftime('%Y-%m-%d %H:%M:%S') if item.end_at else '未设置'}",
                f"中标用户：{item.winner_user_id or '未结算'}",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回列表", callback_data=f"auc:list:{chat_id}:0")]]),
        )

    async def _handle_auction(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_auction_menu(update, context, chat_id)
            return
        if action == "list":
            await self._show_auction_list(update, context, chat_id, callback_data.get_int_optional(3) or 0)
            return
        if action == "detail":
            await self._show_auction_detail(update, context, chat_id, callback_data.get_int(3))
            return

        async with db.session_factory() as session:
            if action == "toggle":
                field = callback_data.get(3)
                enabled = callback_data.get(4) == "1"
                updates = {
                    "enabled": enabled,
                    "pin_message_enabled": enabled if field == "pin" else None,
                    "auto_extend_enabled": enabled if field == "auto_extend" else None,
                }
                if field == "enabled":
                    updates = {"enabled": enabled}
                elif field == "pin":
                    updates = {"pin_message_enabled": enabled}
                elif field == "auto_extend":
                    updates = {"auto_extend_enabled": enabled}
                await update_auction_setting(session, chat_id, **updates)
            elif action == "perm":
                await update_auction_setting(session, chat_id, create_permission=callback_data.get(3))
            elif action == "points_mode":
                await update_auction_setting(session, chat_id, points_mode=callback_data.get(3))
            await session.commit()
        await self._show_auction_menu(update, context, chat_id)

    async def _show_bottom_button_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await get_bottom_button_setting(session, chat_id)
            layouts = await list_bottom_button_layouts(session, chat_id)
            await session.commit()
        text = "\n".join(
            [
                "⌨️ 底部按钮",
                "",
                f"⚙️ 状态：{'✅ 启用' if setting.enabled else '❌ 关闭'}",
                f"📝 文案：{setting.header_text}",
                f"🔢 按钮数：{len(layouts)}",
                f"⏱ 重复生成：{'✅ 启用' if setting.repeat_generate_enabled else '❌ 关闭'}",
                "",
                "提示：发送模式会由 Bot 直接发出内容；填充模式会把内容填到当前输入框。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"btm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启用" if setting.enabled else "启用", callback_data=f"btm:toggle:{chat_id}:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.enabled else "关闭", callback_data=f"btm:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("✏️ 文案设置", callback_data=f"btm:text:{chat_id}:edit"),
                InlineKeyboardButton("⌨️ 按钮设置", callback_data=f"btm:layout:{chat_id}:edit"),
            ],
            [
                InlineKeyboardButton("✅ 立刻生成", callback_data=f"btm:generate:{chat_id}:now"),
                InlineKeyboardButton(("✅ " if setting.repeat_generate_enabled else "⏱ ") + "重复生成", callback_data=f"btm:repeat:{chat_id}:{0 if setting.repeat_generate_enabled else 1}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_bottom_button_layout_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            layouts = await compact_bottom_button_layouts(session, chat_id)
            await session.commit()

        grid: list[list[InlineKeyboardButton]] = []
        position_map = {(item.row_no, item.col_no): item for item in layouts}
        max_row = max([item.row_no for item in layouts], default=1)
        for row_no in range(1, min(max_row + 1, 3) + 1):
            row: list[InlineKeyboardButton] = []
            for col_no in range(1, 5):
                item = position_map.get((row_no, col_no))
                if item is None:
                    row.append(InlineKeyboardButton("➕ 按钮", callback_data=f"btm:layout:{chat_id}:add"))
                else:
                    row.append(InlineKeyboardButton(item.button_text, callback_data=f"btm:button:{chat_id}:detail:{item.id}"))
            grid.append(row)
        keyboard_rows = [
            *grid,
            [
                InlineKeyboardButton("♻️ 清空按钮", callback_data=f"btm:layout:{chat_id}:clear"),
                InlineKeyboardButton("🔙 返回", callback_data=f"btm:home:{chat_id}"),
            ],
        ]
        text = "\n".join(
            [
                "⌨️ 底部按钮 | 按钮设置",
                "",
                "先配置按钮布局（每行最多4个按钮）再点击按钮配置文案。",
                "",
                build_management_layout_preview(layouts),
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_bottom_button_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        layout_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            layout = await get_bottom_button_layout(session, chat_id, layout_id)
            await session.commit()
        if layout is None:
            await answer_callback_query_safely(update, "❌ 按钮不存在", show_alert=True)
            await self._show_bottom_button_layout_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "⌨️ 底部按钮 | 编辑按钮",
                "",
                f"按钮文字：{layout.button_text}",
                f"发送内容：{layout.payload_text or layout.button_text}",
                f"当前模式：{'📨 直接发送' if layout.action_mode == 'send' else '✍️ 仅填充'}",
                "",
                "建议按钮文字不超过 4 个字。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ 修改文字", callback_data=f"btm:button:{chat_id}:text:{layout.id}"),
                InlineKeyboardButton("📝 修改内容", callback_data=f"btm:button:{chat_id}:payload:{layout.id}"),
            ],
            [
                InlineKeyboardButton("📨 直接发送" + (" ✅" if layout.action_mode == "send" else ""), callback_data=f"btm:button:{chat_id}:mode:{layout.id}:send"),
                InlineKeyboardButton("✍️ 仅填充" + (" ✅" if layout.action_mode == "fill" else ""), callback_data=f"btm:button:{chat_id}:mode:{layout.id}:fill"),
            ],
            [
                InlineKeyboardButton("❌ 删除按钮", callback_data=f"btm:button:{chat_id}:delete:{layout.id}"),
                InlineKeyboardButton("🔙 返回", callback_data=f"btm:layout:{chat_id}:edit"),
            ],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _handle_bottom_button(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_bottom_button_menu(update, context, chat_id)
            return

        async with db.session_factory() as session:
            if action == "toggle":
                await update_bottom_button_setting(session, chat_id, enabled=callback_data.get(3) == "1")
                await session.commit()
                await self._show_bottom_button_menu(update, context, chat_id)
                return
            if action == "text" and callback_data.get(3) == "edit":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    update.effective_user.id,
                    "bottom_button_text_input",
                    {"target_chat_id": chat_id},
                )
                setting = await get_bottom_button_setting(session, chat_id)
                await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    f"⌨️ 底部按钮 | 修改文本内容\n\n当前的文本内容：\n{setting.header_text}\n\n👉 现在输入新的文本内容：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"btm:home:{chat_id}")]]),
                )
                return
            if action == "layout":
                sub = callback_data.get(3)
                if sub == "edit":
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
                if sub == "add":
                    await add_layout_button(session, chat_id)
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
                if sub == "clear":
                    await clear_bottom_button_layouts(session, chat_id)
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
            if action == "button":
                sub = callback_data.get(3)
                layout_id = callback_data.get_int(4)
                if sub == "detail":
                    await session.commit()
                    await self._show_bottom_button_detail(update, context, chat_id, layout_id)
                    return
                if sub == "mode":
                    await update_layout_button(session, chat_id=chat_id, layout_id=layout_id, action_mode=callback_data.get(5))
                    await session.commit()
                    await self._show_bottom_button_detail(update, context, chat_id, layout_id)
                    return
                if sub == "delete":
                    await delete_layout_button(session, chat_id, layout_id)
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
                if sub in {"text", "payload"}:
                    state_type = "bottom_button_button_text_input" if sub == "text" else "bottom_button_payload_input"
                    await self._start_text_input_state(
                        context,
                        update.effective_user.id,
                        update.effective_user.id,
                        state_type,
                        {"target_chat_id": chat_id, "layout_id": layout_id},
                    )
                    await session.commit()
                    prompt = "👉 现在输入按钮文字：" if sub == "text" else "👉 现在输入按钮发送内容："
                    await self.message_helper.safe_edit(
                        update,
                        ("⌨️ 底部按钮 | 编辑按钮文字" if sub == "text" else "⌨️ 底部按钮 | 编辑按钮内容") + f"\n\n{prompt}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"btm:button:{chat_id}:detail:{layout_id}")]]),
                    )
                    return
            if action == "generate" and callback_data.get(3) == "now":
                await update_bottom_button_setting(session, chat_id, enabled=True)
                await generate_bottom_buttons(context, session, chat_id)
                await session.commit()
                await self._show_bottom_button_menu(update, context, chat_id)
                return
            if action == "repeat":
                await update_bottom_button_setting(session, chat_id, repeat_generate_enabled=callback_data.get(3) == "1")
                await session.commit()
                await self._show_bottom_button_menu(update, context, chat_id)
                return

    async def _show_game_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await get_game_setting(session, chat_id)
            rake_owner = await get_game_rake_owner_label(session, setting.rake_owner_user_id)
            await session.commit()
        chat_title = await self._get_chat_title(db, chat_id)
        text = format_game_menu_text(
            chat_title,
            k3_enabled=setting.k3_enabled,
            blackjack_enabled=setting.blackjack_enabled,
            rake_ratio=setting.rake_ratio,
            rake_owner=rake_owner,
            auto_schedule_enabled=setting.auto_schedule_enabled,
            auto_start_time=setting.auto_start_time,
            auto_stop_time=setting.auto_stop_time,
            delete_mode=setting.delete_game_message_mode,
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎲 快3", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.k3_enabled else "启动", callback_data=f"gm:toggle:{chat_id}:k3:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.k3_enabled else "关闭", callback_data=f"gm:toggle:{chat_id}:k3:0"),
            ],
            [
                InlineKeyboardButton("🃏 黑杰克", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.blackjack_enabled else "启动", callback_data=f"gm:toggle:{chat_id}:blackjack:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.blackjack_enabled else "关闭", callback_data=f"gm:toggle:{chat_id}:blackjack:0"),
            ],
            [
                InlineKeyboardButton("💧 抽水比例", callback_data=f"gm:rake:{chat_id}:ratio"),
                InlineKeyboardButton("👤 抽水归属", callback_data=f"gm:rake:{chat_id}:owner"),
            ],
            [
                InlineKeyboardButton("⏰ 定时启停", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.auto_schedule_enabled else "启动", callback_data=f"gm:auto:{chat_id}:toggle:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.auto_schedule_enabled else "关闭", callback_data=f"gm:auto:{chat_id}:toggle:0"),
            ],
            [
                InlineKeyboardButton("🕒 启动时间", callback_data=f"gm:auto:{chat_id}:start_time"),
                InlineKeyboardButton("🌙 关停时间", callback_data=f"gm:auto:{chat_id}:stop_time"),
            ],
            [
                InlineKeyboardButton("🧹 删除游戏消息：", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("🗑 删除" + (" ✅" if setting.delete_game_message_mode == "delete" else ""), callback_data=f"gm:delete_mode:{chat_id}:delete"),
                InlineKeyboardButton("💾 不删除" + (" ✅" if setting.delete_game_message_mode == "keep" else ""), callback_data=f"gm:delete_mode:{chat_id}:keep"),
            ],
            [
                InlineKeyboardButton("📋 最近牌局", callback_data=f"gm:rounds:{chat_id}"),
                InlineKeyboardButton("📘 指令帮助", callback_data=f"gm:help:{chat_id}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_game_rounds(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        async with context.application.bot_data["db"].session_factory() as session:
            rounds = await list_recent_game_rounds(session, chat_id, limit=8)
            await session.commit()
        lines = ["📋 最近牌局", ""]
        if not rounds:
            lines.append("暂无牌局记录。")
        else:
            for round_obj in rounds:
                lines.append(
                    f"• #{round_obj.id} | {round_obj.game_type} | {round_obj.status} | {round_obj.created_at.strftime('%m-%d %H:%M')}"
                )
        keyboard_rows = [
            [InlineKeyboardButton(f"🔎 查看 #{round_obj.id}", callback_data=f"gm:detail:{chat_id}:{round_obj.id}")]
            for round_obj in rounds
        ]
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_game_round_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        round_id: int,
    ) -> None:
        async with context.application.bot_data["db"].session_factory() as session:
            rounds = await list_recent_game_rounds(session, chat_id, limit=50)
            round_obj = next((item for item in rounds if item.id == round_id), None)
            participants = await get_game_round_participants(session, round_id)
            await session.commit()
        if round_obj is None:
            await self.message_helper.safe_edit(
                update,
                "未找到该牌局。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:rounds:{chat_id}")]]),
            )
            return
        result_data = round_obj.result_data or {}
        lines = [
            "🎮 牌局详情",
            "",
            f"🆔 局号：{round_obj.id}",
            f"🎯 类型：{round_obj.game_type}",
            f"📌 状态：{round_obj.status}",
            f"🕒 创建时间：{round_obj.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if round_obj.game_type == "k3":
            lines.append(f"🎲 开奖结果：{result_data.get('dice') or '未开奖'}")
            if result_data.get("label"):
                lines.append(f"🏷 结果标签：{result_data.get('label')}")
        if round_obj.game_type == "blackjack":
            lines.append(f"🃏 玩家牌：{result_data.get('player_cards') or []}")
            lines.append(f"🤖 庄家牌：{result_data.get('dealer_cards') or []}")
        lines.append("")
        lines.append("👥 参与情况：")
        if participants:
            for participant in participants:
                lines.append(
                    f"• 用户 {participant.user_id} | 下注 {participant.bet_points} | 状态 {participant.status} | 结算 {participant.payout_points}"
                )
        else:
            lines.append("• 暂无参与记录")
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:rounds:{chat_id}")]]),
        )

    async def _show_game_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        text = "\n".join(
            [
                "📘 游戏指令帮助",
                "",
                "🎲 快3：",
                "• 发送 `快3` 查看玩法",
                "• 发送 `快3 大 100` / `快3 小 100` / `快3 单 100` / `快3 双 100` / `快3 豹子 100` 下注",
                "",
                "🃏 黑杰克：",
                "• 发送 `黑杰克` 查看玩法",
                "• 发送 `黑杰克 100` 开局",
                "• 发送 `要牌` / `停牌` 继续本局",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]),
        )

    async def _handle_game(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_game_menu(update, context, chat_id)
            return
        if action == "rounds":
            await self._show_game_rounds(update, context, chat_id)
            return
        if action == "detail":
            await self._show_game_round_detail(update, context, chat_id, callback_data.get_int(3, default=0))
            return
        if action == "help":
            await self._show_game_help(update, context, chat_id)
            return
        async with db.session_factory() as session:
            if action == "toggle":
                field = callback_data.get(3)
                enabled = callback_data.get(4) == "1"
                await update_game_setting(session, chat_id, **{f"{field}_enabled": enabled})
                await session.commit()
                await self._show_game_menu(update, context, chat_id)
                return
            if action == "rake":
                sub = callback_data.get(3)
                if sub == "ratio":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_rake_ratio", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "🎮 游戏 | 抽水比例\n\n请输入抽水比例\n例如：0.1 就是抽水10%", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]))
                    return
                if sub == "owner":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_rake_owner", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "🎮 游戏 | 抽水归属\n\n请输入用户名或用户ID，发送“清空”可注销抽水归属。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]))
                    return
            if action == "auto":
                sub = callback_data.get(3)
                if sub == "toggle":
                    await update_game_setting(session, chat_id, auto_schedule_enabled=callback_data.get(4) == "1")
                elif sub == "start_time":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_auto_start_time", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "🎮 游戏 | 自动启动时间\n\n游戏自动启动时间 格式:时:分 例如:23:05", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]))
                    return
                elif sub == "stop_time":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_auto_stop_time", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "🎮 游戏 | 自动关停时间\n\n游戏自动关停时间 格式:时:分", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]))
                    return
                await session.commit()
                await self._show_game_menu(update, context, chat_id)
                return
            if action == "delete_mode":
                await update_game_setting(session, chat_id, delete_game_message_mode=callback_data.get(3))
                await session.commit()
                await self._show_game_menu(update, context, chat_id)
                return

    async def _show_guess_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            counts = await count_events_by_status(session, chat_id)
            await session.commit()
        text = "\n".join(
            [
                "⚽ 竞猜",
                "",
                f"🟡 待开奖：{counts['pending']}",
                f"🟢 进行中：{counts['running']}",
                f"✅ 已开奖：{counts['opened']}",
                f"❌ 已取消：{counts['cancelled']}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 发起竞猜", callback_data=f"guess:create:{chat_id}:start")],
            [
                InlineKeyboardButton(f"🟡 待开奖 ({counts['pending']})", callback_data=f"guess:list:{chat_id}:pending"),
                InlineKeyboardButton(f"🟢 进行中 ({counts['running']})", callback_data=f"guess:list:{chat_id}:running"),
            ],
            [
                InlineKeyboardButton(f"✅ 已开奖 ({counts['opened']})", callback_data=f"guess:list:{chat_id}:opened"),
                InlineKeyboardButton(f"❌ 已取消 ({counts['cancelled']})", callback_data=f"guess:list:{chat_id}:cancelled"),
            ],
            [
                InlineKeyboardButton("⚙️ 规则设置", callback_data=f"guess:settings:{chat_id}:home"),
                InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}"),
            ],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_guess_create_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        draft: dict,
    ) -> None:
        text = format_event_preview(draft)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏷️ 活动名字", callback_data=f"guess:create:{chat_id}:title"),
                InlineKeyboardButton("🖼️ 活动封面", callback_data=f"guess:create:{chat_id}:cover"),
                InlineKeyboardButton("📝 活动说明", callback_data=f"guess:create:{chat_id}:description"),
            ],
            [
                InlineKeyboardButton("👑 本局庄家", callback_data=f"guess:create:{chat_id}:banker"),
                InlineKeyboardButton("🏦 公共奖池", callback_data=f"guess:create:{chat_id}:pool"),
                InlineKeyboardButton("🎯 竞猜选项", callback_data=f"guess:create:{chat_id}:options"),
            ],
            [
                InlineKeyboardButton("⌨️ 群内指令", callback_data=f"guess:create:{chat_id}:command"),
                InlineKeyboardButton("⏰ 截止时间", callback_data=f"guess:create:{chat_id}:deadline"),
                InlineKeyboardButton(("✅ " if draft.get("allow_repeat_bet") else "❌ ") + "下注限制", callback_data=f"guess:create:{chat_id}:repeat"),
            ],
            [
                InlineKeyboardButton("👀 预览效果", callback_data=f"guess:create:{chat_id}:preview"),
                InlineKeyboardButton("✅ 发布活动", callback_data=f"guess:create:{chat_id}:publish"),
            ],
            [
                InlineKeyboardButton("♻️ 清空配置", callback_data=f"guess:create:{chat_id}:clear"),
                InlineKeyboardButton("🔙 返回", callback_data=f"guess:home:{chat_id}"),
            ],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_guess_settings(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await get_guess_setting(session, chat_id)
            owner_label = await get_game_rake_owner_label(session, setting.rake_owner_user_id)
            await session.commit()
        text = "\n".join(
            [
                "⚽ 竞猜 | 规则设置",
                "",
                f"💧 抽水比例：{setting.rake_ratio or '未设置'}",
                f"👤 抽水归属：{owner_label}",
                f"🧹 删除消息：{'🗑 删除' if setting.delete_message_mode == 'delete' else '💾 不删除'}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💧 抽水比例", callback_data=f"guess:settings:{chat_id}:rake_ratio"),
                InlineKeyboardButton("👤 抽水归属", callback_data=f"guess:settings:{chat_id}:rake_owner"),
            ],
            [
                InlineKeyboardButton("🗑 删除消息" + (" ✅" if setting.delete_message_mode == "delete" else ""), callback_data=f"guess:settings:{chat_id}:delete_mode:delete"),
                InlineKeyboardButton("💾 不删除" + (" ✅" if setting.delete_message_mode == "keep" else ""), callback_data=f"guess:settings:{chat_id}:delete_mode:keep"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"guess:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_guess_event_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        status: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            events = await list_guess_events(session, chat_id, status)
            await session.commit()
        lines = [f"⚽ 竞猜 | {status}", ""]
        if events:
            for event in events:
                lines.append(f"#{event.id} {event.title}｜{event.command_keyword}｜{event.deadline_at.astimezone().strftime('%m-%d %H:%M')}")
        else:
            lines.append("暂无数据")
        keyboard_rows = [[InlineKeyboardButton(f"📄 {event.title}", callback_data=f"guess:detail:{chat_id}:{event.id}")] for event in events]
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"guess:home:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_guess_event_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        event_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            event = await get_guess_event(session, chat_id, event_id)
            await session.commit()
        if event is None:
            await answer_callback_query_safely(update, "❌ 活动不存在", show_alert=True)
            await self._show_guess_home(update, context, chat_id)
            return
        keyboard_rows = []
        if event.status in {"pending", "running"}:
            open_buttons = [
                InlineKeyboardButton(f"🏁 开 {item['key']}", callback_data=f"guess:open:{chat_id}:{event.id}:{item['key']}")
                for item in (event.options_json or [])
            ]
            keyboard_rows.extend([open_buttons[i:i+2] for i in range(0, len(open_buttons), 2)])
            keyboard_rows.append([InlineKeyboardButton("❌ 取消活动", callback_data=f"guess:cancel:{chat_id}:{event.id}")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"guess:list:{chat_id}:{event.status}")])
        await self.message_helper.safe_edit(update, format_event_runtime(event), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _handle_guess(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_guess_home(update, context, chat_id)
            return
        async with db.session_factory() as session:
            if action == "create":
                sub = callback_data.get(3)
                state = await get_user_state(session, update.effective_user.id, update.effective_user.id)
                draft = dict((state.state_data or {}) if state and state.state_type.startswith("guess_wait_") else {})
                if sub == "start":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "guess_wait_title", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "⚽ 竞猜 | 活动名字\n\n👉 请输入活动名字：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:home:{chat_id}")]]))
                    return
                if sub in {"title", "cover", "description", "banker", "pool", "options", "command", "deadline"}:
                    state_map = {
                        "title": "guess_wait_title",
                        "cover": "guess_wait_cover",
                        "description": "guess_wait_description",
                        "banker": "guess_wait_banker",
                        "pool": "guess_wait_pool",
                        "options": "guess_wait_options",
                        "command": "guess_wait_command",
                        "deadline": "guess_wait_deadline",
                    }
                    prompt_map = {
                        "title": "⚽ 竞猜 | 活动名字\n\n👉 请输入活动名字：",
                        "cover": "⚽ 竞猜 | 活动封面\n\n请发送图片，或发送“清空”移除封面。",
                        "description": "⚽ 竞猜 | 活动说明\n\n👉 请输入活动说明：",
                        "banker": "⚽ 竞猜 | 本局庄家\n\n请输入用户名或用户ID，发送“清空”切回无庄模式。",
                        "pool": "⚽ 竞猜 | 公共奖池\n\n👉 请输入公共奖池积分：",
                        "options": "⚽ 竞猜 | 竞猜选项\n\n每行一个选项，支持 `编号:文案`。",
                        "command": "⚽ 竞猜 | 群内指令\n\n👉 请输入群内指令，例如：竞猜",
                        "deadline": "⚽ 竞猜 | 截止时间\n\n请输入分钟数或 HH:MM，例如 30 / 23:05",
                    }
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, state_map[sub], {"target_chat_id": chat_id, **draft})
                    await session.commit()
                    await self.message_helper.safe_edit(update, prompt_map[sub], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:create:{chat_id}:preview")]]))
                    return
                if sub == "repeat":
                    draft["allow_repeat_bet"] = not bool(draft.get("allow_repeat_bet", False))
                    await set_user_state(session, update.effective_user.id, update.effective_user.id, "guess_wait_title", {"target_chat_id": chat_id, **draft})
                    await session.commit()
                    await self._show_guess_create_menu(update, context, chat_id, draft)
                    return
                if sub == "clear":
                    await clear_user_state(session, update.effective_user.id, update.effective_user.id)
                    await session.commit()
                    await self._show_guess_create_menu(update, context, chat_id, {})
                    return
                if sub == "preview":
                    await session.commit()
                    await self._show_guess_create_menu(update, context, chat_id, draft)
                    return
                if sub == "publish":
                    required = {"title", "options", "command_keyword", "deadline_at"}
                    if not required.issubset(set(draft.keys())):
                        await session.commit()
                        await answer_callback_query_safely(update, "❌ 请先补齐活动名字、竞猜选项、群内指令和截止时间。", show_alert=True)
                        return
                    event = await create_guess_event(session, chat_id, update.effective_user.id, draft)
                    sent = await context.bot.send_message(chat_id=chat_id, text=format_event_runtime(event), parse_mode="Markdown")
                    event.announcement_message_id = sent.message_id
                    await clear_user_state(session, update.effective_user.id, update.effective_user.id)
                    await session.commit()
                    await self._show_guess_event_detail(update, context, chat_id, event.id)
                    return
            if action == "settings":
                sub = callback_data.get(3)
                if sub == "home":
                    await session.commit()
                    await self._show_guess_settings(update, context, chat_id)
                    return
                if sub == "rake_ratio":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "guess_wait_rake_ratio", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "⚽ 竞猜 | 抽水比例\n\n请输入 0 到 1 之间的小数，例如 0.1。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:settings:{chat_id}:home")]]))
                    return
                if sub == "rake_owner":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "guess_wait_rake_owner", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "⚽ 竞猜 | 抽水归属\n\n请输入用户名或用户ID，发送“清空”清除。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:settings:{chat_id}:home")]]))
                    return
                if sub == "delete_mode":
                    await update_guess_setting(session, chat_id, delete_message_mode=callback_data.get(4))
                    await session.commit()
                    await self._show_guess_settings(update, context, chat_id)
                    return
            if action == "list":
                await session.commit()
                await self._show_guess_event_list(update, context, chat_id, callback_data.get(3))
                return
            if action == "detail":
                await session.commit()
                await self._show_guess_event_detail(update, context, chat_id, callback_data.get_int(3))
                return
            if action == "open":
                event = await get_guess_event(session, chat_id, callback_data.get_int(3))
                if event is None:
                    await session.commit()
                    await answer_callback_query_safely(update, "❌ 活动不存在", show_alert=True)
                    return
                note = await settle_guess_event(session, event=event, winner_option=callback_data.get(4))
                await context.bot.send_message(chat_id=chat_id, text=f"{format_event_runtime(event)}\n\n{note}", parse_mode="Markdown")
                await session.commit()
                await self._show_guess_event_detail(update, context, chat_id, event.id)
                return
            if action == "cancel":
                event = await get_guess_event(session, chat_id, callback_data.get_int(3))
                if event is None:
                    await session.commit()
                    await answer_callback_query_safely(update, "❌ 活动不存在", show_alert=True)
                    return
                await cancel_guess_event(session, event=event)
                await session.commit()
                await self._show_guess_event_detail(update, context, chat_id, event.id)
                return

    async def _show_engagement_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            counts = await get_egg_event_counts(session, chat_id)
            latest_running = await get_latest_running_egg_event(session, chat_id)
            reward = await get_engagement_chat_reward(session, chat_id)
            recent_stats = await get_recent_chat_reward_stats(session, chat_id, days=7)
            await session.commit()
        reward_type_label = "📈 递增奖励" if reward.reward_type == "daily_increment" else "🔁 周期奖励"
        recent_claims = sum(item["claim_count"] for item in recent_stats)
        text = "\n".join(
            [
                "✨ 促活工具",
                "",
                f"🥚 彩蛋活动：📋 总数 {counts['all']} | 🟢 运行中 {counts['running']} | ✅ 已结束 {counts['finished']}",
                (
                    f"🧩 当前活动：{latest_running.title} | 线索 {latest_running.published_clue_count}/{len(latest_running.clues or [])}"
                    if latest_running is not None
                    else "🧩 当前活动：暂无运行中的彩蛋"
                ),
                f"💬 水群激励：{'✅ 开启' if reward.enabled else '❌ 关闭'} | {reward_type_label}",
                f"🎯 发言目标：{reward.daily_message_target}",
                f"⌨️ 领奖口令：{reward.command_keyword}",
                f"📊 近7日领取次数：{recent_claims}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🥚 彩蛋活动", callback_data=f"act:egg:{chat_id}:list:all"),
                InlineKeyboardButton("💬 水群激励", callback_data=f"act:chat:{chat_id}:home"),
            ],
            [
                InlineKeyboardButton("📚 彩蛋历史", callback_data=f"act:egg:{chat_id}:history"),
                InlineKeyboardButton("📈 近7日统计", callback_data=f"act:chat:{chat_id}:stats"),
                InlineKeyboardButton("🧾 领奖记录", callback_data=f"act:chat:{chat_id}:history"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_egg_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        status: str = "all",
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            counts = await get_egg_event_counts(session, chat_id)
            events = await list_egg_events(session, chat_id, status=status, limit=12)
            await session.commit()
        lines = [
            "🥚 有奖彩蛋 | 活动列表",
            "",
            f"📋 全部 {counts['all']} | ⚪ 草稿/暂停 {counts['idle']} | 🟢 运行中 {counts['running']} | ✅ 已结束 {counts['finished']}",
            "",
        ]
        if not events:
            lines.append("• 当前筛选下暂无活动")
        else:
            for event in events:
                status_icon = {"idle": "⚪", "running": "🟢", "finished": "✅"}.get(event.status, "⚪")
                lines.append(
                    f"• #{event.id} {status_icon} {event.title} | 线索 {event.published_clue_count}/{len(event.clues or [])} | {'✅ 开启' if event.enabled else '❌ 关闭'}"
                )
        keyboard_rows = [
            [
                InlineKeyboardButton("🆕 新建活动", callback_data=f"act:egg:{chat_id}:new"),
                InlineKeyboardButton("📚 历史记录", callback_data=f"act:egg:{chat_id}:history"),
            ],
            [
                InlineKeyboardButton("✅ 全部" if status == "all" else "全部", callback_data=f"act:egg:{chat_id}:list:all"),
                InlineKeyboardButton("✅ 运行中" if status == "running" else "运行中", callback_data=f"act:egg:{chat_id}:list:running"),
                InlineKeyboardButton("✅ 已结束" if status == "finished" else "已结束", callback_data=f"act:egg:{chat_id}:list:finished"),
            ],
        ]
        for event in events[:8]:
            keyboard_rows.append(
                [InlineKeyboardButton(f"🔎 #{event.id} {event.title[:18]}", callback_data=f"act:egg:{chat_id}:detail:{event.id}")]
            )
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"act:home:{chat_id}")])
        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_engagement_egg(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        event_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            event = await get_egg_event(session, chat_id, event_id)
            await session.commit()
        if event is None:
            await self.message_helper.safe_edit(
                update,
                "❌ 彩蛋活动不存在或已删除。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:list:all")]]),
            )
            return
        clues = event.clues or []
        rewards = event.clue_rewards or []
        clue_times = event.clue_times or []
        status_icon = {"idle": "⚪", "running": "🟢", "finished": "✅"}.get(event.status, "⚪")
        reward_preview = " / ".join(str(item) for item in rewards) if rewards else "未配置"
        time_preview = " / ".join(clue_times) if clue_times else "未配置"
        answer_preview = event.answer or "未配置"
        winner_preview = str(event.winner_user_id) if event.winner_user_id else "暂无"
        text = "\n".join(
            [
                f"🥚 有奖彩蛋 | #{event.id} {event.title}",
                "",
                f"📌 状态：{'✅ 开启' if event.enabled else '❌ 关闭'}",
                f"🚦 运行态：{status_icon} {event.status}",
                f"🔐 当前答案：{answer_preview}",
                f"🧩 线索数量：{len(clues)}/4",
                f"📤 已发布线索：{event.published_clue_count}/{len(clues)}",
                f"🎁 奖励数组：{reward_preview}",
                f"⏰ 发布时间：{time_preview}",
                f"🏆 当前中奖者：{winner_preview}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(("✅ 状态" if event.enabled else "❌ 状态"), callback_data=f"act:egg:{chat_id}:toggle:{event.id}:{0 if event.enabled else 1}"),
                InlineKeyboardButton("🧩 编辑模板", callback_data=f"act:egg:{chat_id}:template:{event.id}"),
            ],
            [
                InlineKeyboardButton("👀 预览配置", callback_data=f"act:egg:{chat_id}:preview:{event.id}"),
                InlineKeyboardButton("📤 立即发布", callback_data=f"act:egg:{chat_id}:publish:{event.id}"),
            ],
            [
                InlineKeyboardButton("⏸ 暂停" if event.status == "running" else "▶️ 恢复", callback_data=f"act:egg:{chat_id}:status:{event.id}:{'idle' if event.status == 'running' else 'running'}"),
                InlineKeyboardButton("♻️ 重置活动", callback_data=f"act:egg:{chat_id}:reset:{event.id}"),
            ],
            [InlineKeyboardButton("🔙 返回列表", callback_data=f"act:egg:{chat_id}:list:all")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_chat_reward(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            reward = await get_engagement_chat_reward(session, chat_id)
            await session.commit()
        plan_preview = " ".join(str(item) for item in (reward.reward_points_plan or [])) or "未配置"
        type_label = "📈 递增奖励" if reward.reward_type == "daily_increment" else "🔁 周期奖励"
        after_7d_label = "♻️ 重置奖励" if reward.after_7d_mode == "reset" else "➡️ 延续奖励"
        text = "\n".join(
            [
                "💬 水群激励",
                "",
                f"📌 状态：{'✅ 开启' if reward.enabled else '❌ 关闭'}",
                f"🎛 奖励类型：{type_label}",
                f"🎯 达标发言：{reward.daily_message_target}",
                f"🎁 七日奖励：{plan_preview}",
                f"🗓 7日后策略：{after_7d_label}",
                f"⌨️ 领奖口令：{reward.command_keyword}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(("✅ 状态" if reward.enabled else "❌ 状态"), callback_data=f"act:chat:{chat_id}:toggle:{0 if reward.enabled else 1}"),
                InlineKeyboardButton(type_label, callback_data=f"act:chat:{chat_id}:type:{'weekly_cycle' if reward.reward_type == 'daily_increment' else 'daily_increment'}"),
            ],
            [
                InlineKeyboardButton("🎯 发言数量", callback_data=f"act:chat:{chat_id}:target"),
                InlineKeyboardButton("🎁 奖励设置", callback_data=f"act:chat:{chat_id}:plan"),
            ],
            [
                InlineKeyboardButton("♻️ 7日后重置" + (" ✅" if reward.after_7d_mode == "reset" else ""), callback_data=f"act:chat:{chat_id}:after7:reset"),
                InlineKeyboardButton("➡️ 7日后延续" + (" ✅" if reward.after_7d_mode == "continue" else ""), callback_data=f"act:chat:{chat_id}:after7:continue"),
            ],
            [
                InlineKeyboardButton("⌨️ 领奖口令", callback_data=f"act:chat:{chat_id}:command"),
                InlineKeyboardButton("👀 预览配置", callback_data=f"act:chat:{chat_id}:preview"),
            ],
            [
                InlineKeyboardButton("📈 近7日统计", callback_data=f"act:chat:{chat_id}:stats"),
                InlineKeyboardButton("🧾 领奖记录", callback_data=f"act:chat:{chat_id}:history"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"act:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_chat_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            stats = await get_recent_chat_reward_stats(session, chat_id, days=7)
            top_users = await get_chat_reward_top_users(session, chat_id, days=7, limit=5)
            await session.commit()
        stat_lines = [f"• {item['biz_date']}: 消息 {item['message_total']} / 领奖 {item['claim_count']} / 发放 {item['reward_total']} 积分" for item in stats] or ["• 暂无统计数据"]
        top_lines = [f"• {item['label']}: {item['message_total']} 条" for item in top_users] or ["• 暂无排行数据"]
        text = "\n".join(
            [
                "📈 水群激励 | 近7日统计",
                "",
                "📊 每日概览：",
                *stat_lines,
                "",
                "🏆 活跃排行：",
                *top_lines,
            ]
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_chat_history(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            claims = await get_recent_chat_reward_claims(session, chat_id, limit=10)
            await session.commit()
        lines = [
            f"• {item['biz_date']} | {item['label']} | 奖励 {item['rewarded_points']} | 连续 {item['streak_days']} 天 | 发言 {item['message_count']}"
            for item in claims
        ] or ["• 暂无领奖记录"]
        text = "\n".join(["🧾 水群激励 | 最近领奖记录", "", *lines])
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_egg_history(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            history_rows = await list_egg_history(session, chat_id, limit=10)
            await session.commit()
        lines = ["📚 有奖彩蛋 | 历史记录", ""]
        if not history_rows:
            lines.append("• 暂无历史记录")
        else:
            for row in history_rows:
                lines.append(
                    f"• {row.created_at.strftime('%Y-%m-%d %H:%M')} | #{row.event_id or '-'} {row.title or '未命名活动'} | 状态 {row.status} | 中奖者 {row.winner_user_id or '暂无'} | 奖励 {row.reward_points}"
                )
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:list:all")]]),
        )

    async def _handle_engagement(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_engagement_home(update, context, chat_id)
            return

        async with db.session_factory() as session:
            if action == "egg":
                sub = callback_data.get(3)
                if sub in {"home", "list"}:
                    await session.commit()
                    await self._show_engagement_egg_list(update, context, chat_id, status=callback_data.get(4, "all") or "all")
                    return
                if sub == "new":
                    await self._start_text_input_state(
                        context,
                        update.effective_user.id,
                        update.effective_user.id,
                        "engagement_wait_egg_template",
                        {"target_chat_id": chat_id},
                    )
                    await session.commit()
                    await self.message_helper.safe_edit(
                        update,
                        (
                            "🥚 有奖彩蛋 | 新建活动\n\n"
                            "请按以下格式发送：\n"
                            "标题=四月彩蛋（可选）\n"
                            "答案=xxx\n线索1=...\n奖励1=100\n时间1=09:00\n"
                            "线索2=...\n奖励2=80\n时间2=10:00\n"
                            "线索3=...\n奖励3=60\n时间3=11:00\n"
                            "线索4=...\n奖励4=40\n时间4=12:00"
                        ),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:list:all")]]),
                    )
                    return
                if sub == "detail":
                    event_id = callback_data.get_int(4)
                    await session.commit()
                    if event_id is None:
                        await self._show_engagement_egg_list(update, context, chat_id)
                        return
                    await self._show_engagement_egg(update, context, chat_id, event_id)
                    return
                if sub == "history":
                    await session.commit()
                    await self._show_engagement_egg_history(update, context, chat_id)
                    return
                if sub == "toggle":
                    event = await get_egg_event(session, chat_id, callback_data.get_int(4))
                    enabled = callback_data.get(5) == "1"
                    if event is None:
                        await session.commit()
                        await self._show_engagement_egg_list(update, context, chat_id)
                        return
                    event.enabled = enabled
                    if enabled and event.answer and event.clues and event.clue_times and event.winner_user_id is None:
                        event.status = "running"
                    elif not enabled and event.status != "finished":
                        event.status = "idle"
                    await session.commit()
                    await self._show_engagement_egg(update, context, chat_id, event.id)
                    return
                if sub == "status":
                    event = await get_egg_event(session, chat_id, callback_data.get_int(4))
                    target_status = callback_data.get(5)
                    if event is None:
                        await session.commit()
                        await self._show_engagement_egg_list(update, context, chat_id)
                        return
                    if target_status == "running" and event.enabled and event.answer and event.clues and event.clue_times and event.winner_user_id is None:
                        event.status = "running"
                    elif target_status == "idle":
                        event.status = "idle"
                    await session.commit()
                    await self._show_engagement_egg(update, context, chat_id, event.id)
                    return
                if sub == "template":
                    event_id = callback_data.get_int(4)
                    await self._start_text_input_state(
                        context,
                        update.effective_user.id,
                        update.effective_user.id,
                        "engagement_wait_egg_template",
                        {"target_chat_id": chat_id, "event_id": event_id},
                    )
                    await session.commit()
                    await self.message_helper.safe_edit(
                        update,
                        (
                            "🥚 有奖彩蛋 | 模板输入\n\n"
                            "请按以下格式发送：\n"
                            "标题=四月彩蛋（可选）\n"
                            "答案=xxx\n线索1=...\n奖励1=100\n时间1=09:00\n"
                            "线索2=...\n奖励2=80\n时间2=10:00\n"
                            "线索3=...\n奖励3=60\n时间3=11:00\n"
                            "线索4=...\n奖励4=40\n时间4=12:00"
                        ),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:detail:{event_id}" if event_id else f"act:egg:{chat_id}:list:all")]]),
                    )
                    return
                if sub == "preview":
                    event = await get_egg_event(session, chat_id, callback_data.get_int(4))
                    await session.commit()
                    if event is None:
                        await self._show_engagement_egg_list(update, context, chat_id)
                        return
                    preview_lines = [
                        f"🥚 有奖彩蛋 | 预览配置 #{event.id}",
                        "",
                        f"🏷 活动标题：{event.title}",
                        f"🔐 答案：{event.answer or '未配置'}",
                        f"🧩 线索：{event.clues or []}",
                        f"🎁 奖励：{event.clue_rewards or []}",
                        f"⏰ 时间：{event.clue_times or []}",
                    ]
                    await self.message_helper.safe_edit(
                        update,
                        "\n".join(preview_lines),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:detail:{event.id}")]]),
                    )
                    return
                if sub == "publish":
                    event_id = callback_data.get_int(4)
                    published = await publish_next_clue(session, chat_id, event_id=event_id)
                    await session.commit()
                    if published is None:
                        await self.message_helper.safe_edit(
                            update,
                            "🥚 当前没有可立即发布的线索，请先启用活动或检查是否已经全部发布。",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:detail:{event_id}" if event_id else f"act:egg:{chat_id}:list:all")]]),
                        )
                        return
                    event, clue_index, clue_text, reward_points = published
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🥚 有奖彩蛋【{event.title}】| 第 {clue_index + 1} 条线索\n"
                            f"🧩 线索：{clue_text}\n"
                            f"🎁 当前命中奖励：{reward_points} 积分"
                        ),
                    )
                    await self._show_engagement_egg(update, context, chat_id, event.id)
                    return
                if sub == "reset":
                    event = await get_egg_event(session, chat_id, callback_data.get_int(4))
                    if event is None:
                        await session.commit()
                        await self._show_engagement_egg_list(update, context, chat_id)
                        return
                    await archive_egg_snapshot(session, event, reward_points=0)
                    event.enabled = False
                    event.answer = None
                    event.clues = []
                    event.clue_rewards = []
                    event.clue_times = []
                    event.winner_user_id = None
                    event.status = "idle"
                    event.published_clue_count = 0
                    await session.commit()
                    await self._show_engagement_egg(update, context, chat_id, event.id)
                    return
                await session.commit()
                await self._show_engagement_egg_list(update, context, chat_id)
                return

            if action == "chat":
                sub = callback_data.get(3)
                if sub == "home":
                    await session.commit()
                    await self._show_engagement_chat_reward(update, context, chat_id)
                    return
                if sub == "toggle":
                    await update_engagement_chat_reward(session, chat_id, enabled=callback_data.get(4) == "1")
                    await session.commit()
                    await self._show_engagement_chat_reward(update, context, chat_id)
                    return
                if sub == "preview":
                    reward = await get_engagement_chat_reward(session, chat_id)
                    await session.commit()
                    preview_text = "\n".join(
                        [
                            "💬 水群激励 | 预览配置",
                            "",
                            f"🎯 达标发言：{reward.daily_message_target}",
                            f"🎁 奖励计划：{reward.reward_points_plan or []}",
                            f"🗓 7日后策略：{reward.after_7d_mode}",
                            f"⌨️ 领奖口令：{reward.command_keyword}",
                        ]
                    )
                    await self.message_helper.safe_edit(
                        update,
                        preview_text,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]]),
                    )
                    return
                if sub == "stats":
                    await session.commit()
                    await self._show_engagement_chat_stats(update, context, chat_id)
                    return
                if sub == "history":
                    await session.commit()
                    await self._show_engagement_chat_history(update, context, chat_id)
                    return
                if sub == "type":
                    await update_engagement_chat_reward(session, chat_id, reward_type=callback_data.get(4))
                    await session.commit()
                    await self._show_engagement_chat_reward(update, context, chat_id)
                    return
                if sub == "after7":
                    await update_engagement_chat_reward(session, chat_id, after_7d_mode=callback_data.get(4))
                    await session.commit()
                    await self._show_engagement_chat_reward(update, context, chat_id)
                    return
                if sub in {"target", "plan", "command"}:
                    state_map = {
                        "target": "engagement_wait_chat_target",
                        "plan": "engagement_wait_chat_plan",
                        "command": "engagement_wait_chat_command",
                    }
                    prompt_map = {
                        "target": "💬 水群激励 | 发言数量\n\n请输入每日发言达标数，例如：200",
                        "plan": "💬 水群激励 | 奖励设置\n\n请输入 7 个非递减整数，用空格分隔。\n例如：10 20 30 40 50 60 70",
                        "command": "💬 水群激励 | 领奖口令\n\n请输入新的领奖口令，例如：我爱水群",
                    }
                    await self._start_text_input_state(
                        context,
                        update.effective_user.id,
                        update.effective_user.id,
                        state_map[sub],
                        {"target_chat_id": chat_id},
                    )
                    await session.commit()
                    await self.message_helper.safe_edit(
                        update,
                        prompt_map[sub],
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]]),
                    )
                    return
                await session.commit()
                await self._show_engagement_chat_reward(update, context, chat_id)
                return

    async def _show_account_inherit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            summary = await build_inherit_summary(session, chat_id)
            await session.commit()
        enabled = bool(summary["enabled"])
        text = "\n".join(
            [
                "💥 炸号继承",
                "",
                f"📌 允许继承：{'✅ 允许' if enabled else '❌ 不允许'}",
                f"⏱️ Token 有效期：{summary['token_expire_minutes']} 分钟",
                f"🎟️ 活跃令牌：{summary['active_tokens']}",
                f"🧾 已使用令牌：{summary['used_tokens']}",
                "",
                "旧号生成一次性 token，新号在私聊里使用 token 继承主积分和自定义积分。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("允许继承：", callback_data=f"inh:manage:{chat_id}"),
                InlineKeyboardButton("允许" + (" ✅" if enabled else ""), callback_data=f"inh:toggle:{chat_id}:1"),
                InlineKeyboardButton("不允许" + (" ✅" if not enabled else ""), callback_data=f"inh:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("🎟️ 旧号生成令牌", callback_data=f"inh:token:gen:{chat_id}"),
                InlineKeyboardButton("🔓 新号使用令牌", callback_data=f"inh:token:use:{chat_id}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_points_mall_order_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        order_id: int,
        *,
        status: str = "all",
        product_id: int | None = None,
    ) -> None:
        normalized_status = status if status in {"all", "created", "fulfilled", "canceled", "refunded"} else "all"
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            order = await PointsExtendedService.get_order(session, chat_id, order_id)
            logs = await PointsExtendedService.list_order_logs(session, order_id=order_id, limit=5)
            await session.commit()
        if order is None:
            await answer_callback_query_safely(update, "订单不存在", show_alert=True)
            await self._show_points_mall_orders_placeholder(update, context, chat_id, product_id=product_id, status=normalized_status)
            return
        log_lines = ["最近操作："]
        if not logs:
            log_lines.append("- 暂无日志")
        else:
            for item in logs:
                payload = item.payload or {}
                operator = payload.get("operator_user_id", "-")
                timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
                log_lines.append(f"- {timestamp}｜{item.action}｜操作人 {operator}")
        text = "\n".join(
            [
                "🧾 管理订单 | 订单详情",
                "",
                f"订单编号：{order.order_id}",
                f"商品编号：{order.product_id}",
                f"购买用户：{order.buyer_user_id}",
                f"所需积分：{order.price_points}",
                f"数量：{order.quantity}",
                f"订单状态：{order.order_status}",
                f"操作人员：{order.operator_user_id or '未处理'}",
                "",
                *log_lines,
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_order_detail_keyboard(
                chat_id,
                order,
                status=normalized_status,
                product_id=product_id,
            ),
        )

    async def _show_custom_point_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        type_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
            await session.commit()
        if item is None:
            await answer_callback_query_safely(update, "❌ 记录不存在", show_alert=True)
            await self._show_custom_points_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "🌐 自定义积分",
                "",
                f"状态：{'✅ 启用' if item.enabled else '❌ 关闭'}",
                f"⚙️ 积分名字： {item.name}",
                f"⚙️ 排行指令： {item.rank_command or '待配置'}",
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=custom_point_detail_keyboard(item, chat_id))

    async def _show_points_level_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        level_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            level = await PointsExtendedService.get_level(session, chat_id, level_id)
            await session.commit()
        if level is None:
            await answer_callback_query_safely(update, "❌ 等级不存在", show_alert=True)
            await self._show_points_level_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "👨‍💻 积分等级 | 配置等级信息",
                "",
                "通过各种激励方法，促进群友持续水群发言",
                "",
                f"等级名称：{level.level_name}",
                f"积分门槛线：{level.point_threshold}",
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=points_level_detail_keyboard(level, chat_id))

    async def _show_points_level_delete_confirm(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        level_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            level = await PointsExtendedService.get_level(session, chat_id, level_id)
            await session.commit()
        if level is None:
            await answer_callback_query_safely(update, "❌ 等级不存在", show_alert=True)
            await self._show_points_level_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "👨‍💻 积分等级 | 删除等级",
                "",
                f"等级名称：{level.level_name}",
                f"积分门槛线：{level.point_threshold}",
                "",
                "确认后将删除当前等级。",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("确认删除", callback_data=f"adm:lvl:{chat_id}:delete:{level_id}")],
                    [InlineKeyboardButton("🔙 返回", callback_data=f"adm:lvl:{chat_id}:detail:{level_id}")],
                ]
            ),
        )

    async def _show_points_mall_product_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        product_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            product = await PointsExtendedService.get_product(session, chat_id, product_id)
            await session.commit()
        if product is None:
            await answer_callback_query_safely(update, "❌ 商品不存在", show_alert=True)
            await self._show_points_mall_products_placeholder(update, context, chat_id)
            return
        text = "\n".join(
            [
                "🛍️ 管理商品 | 编辑商品",
                "",
                f"🎁 商品名称： {product.name}",
                f"🖼️ 封面设置： {'【等待设置】' if not product.cover_file_id else '【已设置】'}",
                f"🪙 兑换价格： {product.price_points}",
                f"📮 限购设置： {'不限制' if not product.limit_per_user else product.limit_per_user}",
                f"🛒 可售数量： {product.stock_left}/{product.stock_total}",
                f"👨 商品发放： {product.fulfiller_user_id or '未设置'}",
                f"↕️ 排序权重： {product.sort_weight}",
                f"⚠️ 兑换说明： {'【等待设置】' if not product.description else '【已设置】'}",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_product_detail_keyboard(product, chat_id),
        )

    async def _show_points_mall_product_preview(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        product_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            product = await PointsExtendedService.get_product(session, chat_id, product_id)
            await session.commit()
        if product is None:
            await answer_callback_query_safely(update, "❌ 商品不存在", show_alert=True)
            await self._show_points_mall_products_placeholder(update, context, chat_id)
            return
        text = "\n".join(
            [
                "🛍️ 管理商品 | 预览效果",
                "",
                f"商品名称：{product.name}",
                f"兑换价格：{product.price_points} 积分",
                f"限购设置：{'不限制' if not product.limit_per_user else product.limit_per_user}",
                f"可售数量：{product.stock_left}/{product.stock_total}",
                f"兑换说明：{product.description or '暂无说明'}",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
            ),
        )

    async def _show_auto_delete_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示删除系统提示配置菜单"""
        from bot.keyboards.admin.auto_delete import auto_delete_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        enabled_keys = [
            bool(getattr(settings, "auto_delete_join", False)),
            bool(getattr(settings, "auto_delete_left", False)),
            bool(getattr(settings, "auto_delete_pinned", False)),
            bool(getattr(settings, "auto_delete_avatar", False)),
            bool(getattr(settings, "auto_delete_title", False)),
            bool(getattr(settings, "auto_delete_anonymous", False)),
        ]
        enabled_labels = [
            label
            for enabled, label in [
                (bool(getattr(settings, "auto_delete_join", False)), "进群"),
                (bool(getattr(settings, "auto_delete_left", False)), "退群"),
                (bool(getattr(settings, "auto_delete_pinned", False)), "置顶"),
                (bool(getattr(settings, "auto_delete_avatar", False)), "头像"),
                (bool(getattr(settings, "auto_delete_title", False)), "群名"),
                (bool(getattr(settings, "auto_delete_anonymous", False)), "匿名消息"),
            ]
            if enabled
        ]
        text = (
            "🧹 删除系统提示\n\n"
            "本功能会自动清除系统提示消息。\n\n"
            f"总开关状态：{'✅ 已生效' if any(enabled_keys) else '❌ 未生效'}\n"
            f"已开启类型：{sum(enabled_keys)}/{len(enabled_keys)}\n"
            f"当前明细：{'、'.join(enabled_labels) if enabled_labels else '暂无'}\n\n"
            "可删除对象：进群 / 退群 / 置顶 / 修改头像 / 修改群名 / 匿名消息。"
        )

        keyboard = auto_delete_config_keyboard(settings, chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_anti_flood_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示防刷屏配置菜单"""
        from bot.handlers.anti_flood_config_handler import format_anti_flood_menu_text
        from bot.keyboards.admin.antispam import anti_flood_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = format_anti_flood_menu_text(chat_title, settings)
        keyboard = anti_flood_config_keyboard(settings, chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_antispam_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示反垃圾配置菜单"""
        from bot.handlers.anti_spam_config_handler import format_anti_spam_menu_text
        from bot.keyboards.admin.antispam import anti_spam_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = format_anti_spam_menu_text(chat_title, settings)
        keyboard = anti_spam_config_keyboard(settings, chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_group_selection(
        self,
        update: Update,
        managed_chats: list,
        current_chat_id: int | None,
    ) -> None:
        """显示群组选择列表"""
        # 使用 keyboards 层创建键盘
        keyboard = create_group_selection_keyboard(managed_chats, current_chat_id)
        text = "🔄 选择要管理的群组："

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=keyboard
        )


# 创建单例实例
_admin_handler = AdminHandler()


# ==================== 适配器函数（供 Router 注册）====================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员命令 - 在群聊中引导到私聊设置"""
    log.info("admin_command_called")

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        log.warning("admin_command_missing_update_data")
        return

    chat = update.effective_chat
    user = update.effective_user

    log.info("admin_command_chat_info", chat_type=chat.type, chat_id=chat.id, user_id=user.id)

    # 群聊中：引导用户到私聊进行设置
    if chat.type != "private":
        log.info("admin_command_group_chat")
        # 检查管理员权限
        try:
            is_admin = await is_user_admin(context, chat.id, user.id)
        except TelegramError as e:
            log.error("admin_command_get_chat_member_failed", error=str(e))
            await update.effective_message.reply_text("无法获取管理员信息，请确保 bot 有读取群成员的权限")
            return

        if not is_admin:
            await update.effective_message.reply_text("此命令仅限管理员使用")
            return

        db: Database = context.application.bot_data["db"]

        # 设置当前管理的群组
        await set_user_current_chat(db, user.id, chat.id)

        # 保存群组信息
        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await session.commit()

        # 使用 keyboards 层创建引导按钮
        keyboard = create_guide_keyboard(context.bot.username)

        # 发送消息
        msg = await update.effective_message.reply_text(
            f"欢迎使用 @{context.bot.username}:\n\n"
            f"1) 点击下方按钮选择设置（仅限管理员）\n"
            f"2) 点击机器人对话框底部[开始]按钮\n\n"
            f"🟩 功能更新提醒: 在机器人私聊中发送 /start 也可打开管理菜单",
            reply_markup=keyboard
        )

        # 10秒后删除消息（保持群组整洁）
        async def delete_later():
            try:
                await asyncio.sleep(10)
                await msg.delete()
            except Exception as e:
                log.warning("delete_message_failed", error=str(e))

        asyncio.create_task(delete_later())
        return

    # 私聊中：显示管理面板
    log.info("admin_command_private_chat")

    try:
        db: Database = context.application.bot_data["db"]

        # 获取用户管理的群组
        log.info("admin_command_fetching_chats", user_id=user.id)
        chats = await get_user_managed_chats(db, user.id, context.bot)
        log.info("admin_command_chats_fetched", user_id=user.id, chat_count=len(chats))

        current_chat_id = await ChatResolver.get_current_chat(db, user.id)
        log.info("admin_command_current_chat", user_id=user.id, current_chat_id=current_chat_id)

        if not chats:
            log.info("admin_command_no_chats")
            await update.effective_message.reply_text(
                "👋 欢迎使用群管理 Bot！\n\n"
                "暂无群组，请先将 bot 添加到群组中并设为管理员..."
            )
            return

        # 如果没有选中的群组，默认选择第一个
        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]  # 第一个群组的 chat_id
            log.info("admin_command_setting_default_chat", user_id=user.id, default_chat_id=current_chat_id)
            await set_user_current_chat(db, user.id, current_chat_id)

        # 显示管理面板
        log.info("admin_command_showing_menu", user_id=user.id, current_chat_id=current_chat_id)
        await _show_private_admin_menu(update, context, current_chat_id)
        log.info("admin_command_menu_shown", user_id=user.id)
    except Exception as e:
        log.exception("admin_command_error", user_id=user.id, error=str(e))
        await update.effective_message.reply_text(
            f"发生错误：{build_public_error_text(e, fallback='请稍后重试')}"
        )


async def _show_private_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """在私聊中显示管理面板（公开接口，供其他模块调用）"""
    await _admin_handler._show_main_menu(update, context, chat_id)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理回调 - 支持群聊内联按钮和私聊管理"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    data = q.data or ""

    log.warning(
        "=== ADMIN_CALLBACK CALLED ===",
        callback_data=data,
        chat_type=update.effective_chat.type,
        user_id=update.effective_user.id,
    )

    # 私聊中的管理回调 - 使用 Handler 处理
    if update.effective_chat.type == "private":
        cb = CallbackParser.parse(data)
        if cb.get(0) in {"adm", "ali", "gfw", "grg", "tsearch", "crv", "auc", "btm", "gm", "guess", "act"}:
            # 提取 target_chat_id（如果有）
            action = cb.get(1)
            log.info("=== ADMIN_CALLBACK_ACTION ===", action=action, cb_parts=[cb.get(i) for i in range(cb.length())])
            target_chat_id = _resolve_private_scoped_target_chat_id(cb)

            log.info("=== ADMIN_CALLBACK_TARGET_CHAT_ID ===", target_chat_id=target_chat_id)

            if target_chat_id is None:
                log.warning("admin_callback_invalid_chat_id", callback_data=data)
                await answer_callback_query_safely(
                    update,
                    "❌ 群组参数无效，请返回重试",
                    show_alert=True,
                )
                return

            # 检查管理员权限（按群级控制策略统一收口）
            if target_chat_id != 0:
                allowed, error_text = await PermissionPolicyService.require_manage(
                    context,
                    target_chat_id,
                    update.effective_user.id,
                    capability="manage",
                )
                if not allowed:
                    await _admin_handler.message_helper.safe_edit(
                        update, error_text or "你没有该群组的管理权限"
                    )
                    return

            # 使用 Handler 处理
            await _admin_handler.process(update, context, target_chat_id)
        return

    # 群聊中的回调（保持向后兼容，用于其他功能模块）
    user = update.effective_user
    chat = update.effective_chat
    is_admin = await is_user_admin(context, chat.id, user.id)
    log.info("admin_permission_check", chat_id=chat.id, user_id=user.id, is_admin=is_admin)
    if not is_admin:
        log.warning("admin_permission_denied", callback_data=data, chat_id=chat.id, user_id=user.id)
        await _admin_handler.message_helper.safe_edit(q, "此操作仅限管理员使用")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        cb = CallbackParser.parse(data)
        if cb.get(1) == "menu":
            menu = cb.get(2)
            if menu == "main":
                await session.commit()
                await _admin_handler.message_helper.safe_edit(q, t(settings.language, "admin.title"), reply_markup=admin_main_menu())
                return

            if menu == "settings":
                await session.commit()
                await _admin_handler.message_helper.safe_edit(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return

            if menu == "verification":
                # 使用 keyboards 层格式化消息
                text = format_verification_menu_text(
                    chat_title="群组",
                    enabled=settings.verification_enabled,
                    verification_mode=settings.verification_mode,
                    timeout_seconds=settings.verification_timeout_seconds,
                    restrict_can_send=settings.verification_restrict_can_send,
                    timeout_action=settings.verification_timeout_action,
                    mute_duration=settings.verification_mute_duration,
                )
                await session.commit()
                await _admin_handler.message_helper.safe_edit(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
                return

        if cb.get(1) == "toggle":
            field = cb.get(2)
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()
                await _admin_handler.message_helper.safe_edit(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return

        if cb.get(1) == "vfy_mode":
            # 验证模式选择
            selected_mode = cb.get(2)
            if selected_mode in ["button", "math", "captcha"]:
                settings.verification_mode = selected_mode
                await session.commit()

            # 使用 keyboards 层格式化消息
            text = format_verification_menu_text(
                chat_title="群组",
                enabled=settings.verification_enabled,
                verification_mode=settings.verification_mode,
                timeout_seconds=settings.verification_timeout_seconds,
                restrict_can_send=settings.verification_restrict_can_send,
                timeout_action=settings.verification_timeout_action,
                mute_duration=settings.verification_mute_duration,
            )
            await _admin_handler.message_helper.safe_edit(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
            return

        await session.commit()


def _is_valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value))


def _parse_force_subscribe_buttons_input(raw_text: str) -> list[list[dict]]:
    text = (raw_text or "").strip()
    if not text:
        raise ValidationError("按钮配置不能为空。")
    if text.startswith("["):
        return json.loads(text)

    rows: list[list[dict]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" not in line:
            raise ValidationError("文本格式错误：每行必须包含“按钮文案|URL”。")
        button_text, button_url = [part.strip() for part in line.split("|", 1)]
        if not button_text or not button_url:
            raise ValidationError("按钮文案和 URL 不能为空。")
        rows.append([{"text": button_text[:32], "url": button_url}])
    if not rows:
        raise ValidationError("未解析到有效按钮。")
    return rows


def _build_force_subscribe_channel_button_preview(value: str | None) -> InlineKeyboardButton | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.startswith("@"):
        return InlineKeyboardButton(normalized, url=f"https://t.me/{normalized[1:]}")
    if normalized.startswith("https://t.me/") or normalized.startswith("http://t.me/"):
        return InlineKeyboardButton(normalized, url=normalized)
    return None


def _build_force_subscribe_preview_markup(settings, chat_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    custom_enabled = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
    custom_buttons = getattr(settings, "force_subscribe_buttons", None) or []
    if custom_enabled and custom_buttons:
        try:
            normalized = ScheduledMessageService.normalize_buttons_config(custom_buttons)
            for row in normalized:
                rows.append([InlineKeyboardButton(item["text"], url=item["url"]) for item in row])
        except Exception:
            rows = []
    if not rows:
        fallback_buttons = [
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_1", None)),
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_2", None)),
        ]
        rows.extend([[button] for button in fallback_buttons if button is not None])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:forcesub:{chat_id}")])
    return InlineKeyboardMarkup(rows)


async def handle_force_subscribe_channel_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from bot.services.state.state_service import clear_user_state

    if update.effective_user is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if update.effective_message is not None and error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await get_chat_settings(session, target_chat_id)

    if state.state_type == "force_subscribe_channel_1_input":
        field = "force_subscribe_bound_channel_1"
        value = message_text.strip()
        setattr(settings, field, None if value in {"", "清空"} else value)
    elif state.state_type == "force_subscribe_channel_2_input":
        field = "force_subscribe_bound_channel_2"
        value = message_text.strip()
        setattr(settings, field, None if value in {"", "清空"} else value)
    elif state.state_type == "force_subscribe_text_input":
        field = "force_subscribe_guide_text"
        value = message_text.strip()
        if not value:
            await update.effective_message.reply_text("文案不能为空。")
            return
        setattr(settings, field, value)
    elif state.state_type == "force_subscribe_buttons_input":
        if message_text.strip() == "清空":
            settings.force_subscribe_buttons = []
            settings.force_subscribe_custom_buttons_enabled = False
        else:
            try:
                buttons = _parse_force_subscribe_buttons_input(message_text)
                settings.force_subscribe_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
                settings.force_subscribe_custom_buttons_enabled = True
            except (json.JSONDecodeError, ValidationError) as exc:
                await update.effective_message.reply_text(f"按钮格式错误：{exc}")
                return
    elif state.state_type == "force_subscribe_cover_input":
        if message_text.strip() == "清空":
            settings.force_subscribe_cover_media_type = None
            settings.force_subscribe_cover_file_id = None
        else:
            message = update.effective_message
            if message.photo:
                settings.force_subscribe_cover_media_type = "photo"
                settings.force_subscribe_cover_file_id = message.photo[-1].file_id
            elif message.video:
                settings.force_subscribe_cover_media_type = "video"
                settings.force_subscribe_cover_file_id = message.video.file_id
            else:
                await update.effective_message.reply_text("请发送图片或视频，或发送“清空”移除封面。")
                return
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler._show_force_subscribe_menu(update, context, target_chat_id)


async def handle_group_lock_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from bot.services.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await get_chat_settings(session, target_chat_id)
    if state.state_type == "group_lock_open_keyword_input":
        settings.group_lock_open_phrase = message_text.strip()
    elif state.state_type == "group_lock_close_keyword_input":
        settings.group_lock_close_phrase = message_text.strip()
    elif state.state_type == "group_lock_open_time_input":
        value = message_text.strip()
        if not _is_valid_hhmm(value):
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM，例如 08:00")
            return
        settings.group_lock_open_time = value
    elif state.state_type == "group_lock_close_time_input":
        value = message_text.strip()
        if not _is_valid_hhmm(value):
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM，例如 02:00")
            return
        settings.group_lock_close_time = value
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler._show_group_lock_menu(update, context, target_chat_id)


async def handle_rename_monitor_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from bot.services.state.state_service import clear_user_state

    if update.effective_user is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if update.effective_message is not None and error_text:
            await update.effective_message.reply_text(error_text)
        return
    settings = await get_chat_settings(session, target_chat_id)
    settings.name_change_monitor_template_text = message_text.strip()
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler._show_rename_monitor_menu(update, context, target_chat_id)


async def handle_welcome_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from bot.services.state.state_service import clear_user_state
    from bot.services.welcome_service import WelcomeService

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    welcome_id = state.state_data.get("welcome_id")
    if not isinstance(welcome_id, int):
        await update.effective_message.reply_text("欢迎配置上下文已失效，请重新进入配置页。")
        return

    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return

    if state.state_type == "welcome_title_input":
        await WelcomeService.update_field(session, target_chat_id, welcome_id, title=message_text)
    elif state.state_type == "welcome_text_input":
        await WelcomeService.update_field(session, target_chat_id, welcome_id, text_content=message_text)
    elif state.state_type == "welcome_buttons_input":
        if message_text.strip() == "清空":
            await WelcomeService.update_field(session, target_chat_id, welcome_id, buttons=[])
        else:
            try:
                buttons = json.loads(message_text)
                await WelcomeService.update_field(session, target_chat_id, welcome_id, buttons=buttons)
            except (json.JSONDecodeError, ValidationError) as exc:
                await update.effective_message.reply_text(f"按钮格式错误：{exc}")
                return
    elif state.state_type == "welcome_cover_input":
        if message_text.strip() == "清空":
            await WelcomeService.update_field(
                session,
                target_chat_id,
                welcome_id,
                cover_media_type=None,
                cover_media_file_id=None,
            )
        else:
            message = update.effective_message
            if message.photo:
                await WelcomeService.update_field(
                    session,
                    target_chat_id,
                    welcome_id,
                    cover_media_type="photo",
                    cover_media_file_id=message.photo[-1].file_id,
                )
            elif message.video:
                await WelcomeService.update_field(
                    session,
                    target_chat_id,
                    welcome_id,
                    cover_media_type="video",
                    cover_media_file_id=message.video.file_id,
                )
            else:
                await update.effective_message.reply_text("请发送图片或视频，或发送“清空”移除封面。")
                return

    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await _admin_handler._show_welcome_detail_menu(update, context, target_chat_id, welcome_id)


async def handle_alliance_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from bot.services.integration.alliance_service import AllianceService
    from bot.services.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return

    try:
        if state.state_type == "alliance_create_name_input":
            alliance, invite_code = await AllianceService.create_alliance(
                session,
                chat_id=target_chat_id,
                operator_user_id=update.effective_user.id,
                name=message_text,
            )
            notice = f"联盟创建成功，邀请码：{invite_code}"
        elif state.state_type == "alliance_join_code_input":
            alliance = await AllianceService.join_alliance(
                session,
                chat_id=target_chat_id,
                operator_user_id=update.effective_user.id,
                invite_code=message_text,
            )
            notice = f"已加入联盟：{alliance.name}"
        else:
            await update.effective_message.reply_text("联盟输入状态异常，请重新进入页面。")
            return
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(notice)
    await _admin_handler._show_alliance_menu(update, context, target_chat_id)


async def handle_garage_forward_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from bot.services.integration.garage_forward_service import GarageForwardService
    from bot.services.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return

    if state.state_type not in {"garage_forward_source_input", "garage_forward_keyword_input"}:
        await update.effective_message.reply_text("车库转发状态异常，请重新进入页面。")
        return

    if state.state_type == "garage_forward_keyword_input":
        keywords = [
            item.strip()
            for chunk in message_text.replace("，", ",").splitlines()
            for item in chunk.replace(",", " ").split()
            if item.strip()
        ]
        normalized_keywords: list[str] = []
        for item in keywords:
            if item not in normalized_keywords:
                normalized_keywords.append(item[:64])

        await GarageForwardService.update_setting(
            session,
            target_chat_id,
            keyword_rules=normalized_keywords,
        )
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text(
            f"已更新关键词规则，共 {len(normalized_keywords)} 条。"
            if normalized_keywords
            else "已清空关键词规则。"
        )
        await _admin_handler._show_garage_forward_prompt(update, context, target_chat_id)
        return

    raw_value = message_text.strip()
    if not raw_value:
        await update.effective_message.reply_text("来源频道不能为空。")
        return

    source_channel_id: int | None = None
    source_name: str | None = None
    remote_chat = None
    if raw_value.lstrip("-").isdigit():
        source_channel_id = int(raw_value)
        try:
            remote_chat = await context.bot.get_chat(source_channel_id)
        except Exception:
            remote_chat = None
    else:
        try:
            remote_chat = await context.bot.get_chat(raw_value)
        except Exception:
            remote_chat = None
        if remote_chat is not None:
            source_channel_id = int(remote_chat.id)
            source_name = getattr(remote_chat, "title", None) or getattr(remote_chat, "username", None)

    if source_channel_id is None:
        await update.effective_message.reply_text("无法识别该频道，请输入频道 ID、用户名或可解析链接。")
        return
    if remote_chat is None or getattr(remote_chat, "type", None) != "channel":
        await update.effective_message.reply_text("来源必须是频道，群组或私聊不能作为车库转发来源。")
        return

    source_name = source_name or getattr(remote_chat, "title", None) or getattr(remote_chat, "username", None)

    await GarageForwardService.add_source(
        session,
        chat_id=target_chat_id,
        source_channel_id=source_channel_id,
        source_name=source_name,
    )
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text("已添加来源频道。")
    await _admin_handler._show_garage_forward_prompt(update, context, target_chat_id)


async def handle_garage_features_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from bot.services.integration.garage_features_service import (
        CarReviewService,
        GarageAuthService,
        TeacherSearchService,
    )
    from bot.services.state.state_service import clear_user_state, set_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return

    async def _clear_state() -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)

    state_type = state.state_type
    text_value = message_text.strip()

    if state_type == "garage_badge_input":
        if not text_value:
            await update.effective_message.reply_text("认证图标不能为空。")
            return
        await GarageAuthService.update_settings(session, target_chat_id, garage_auth_badge=text_value[:16])
        await _clear_state()
        await session.commit()
        await _admin_handler._show_garage_auth_menu(update, context, target_chat_id)
        return

    if state_type == "garage_teacher_input":
        try:
            await GarageAuthService.add_teacher(session, target_chat_id, update.effective_user.id, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await _clear_state()
        await session.commit()
        await _admin_handler._show_garage_teacher_list_menu(update, context, target_chat_id, 0)
        return

    if state_type == "garage_whitelist_input":
        try:
            await GarageAuthService.add_whitelist(session, target_chat_id, update.effective_user.id, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await _clear_state()
        await session.commit()
        await _admin_handler._show_garage_whitelist_menu(update, context, target_chat_id, 0)
        return

    if state_type in {"garage_limit_interval_input", "garage_limit_max_count_input", "car_review_reward_points_input"}:
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("请输入正整数。")
            return
        number = int(text_value)
        if state_type == "garage_limit_interval_input":
            await GarageAuthService.update_settings(session, target_chat_id, garage_limit_interval_sec=number)
            await _clear_state()
            await session.commit()
            await _admin_handler._show_garage_auth_menu(update, context, target_chat_id)
            return
        if state_type == "garage_limit_max_count_input":
            await GarageAuthService.update_settings(session, target_chat_id, garage_limit_max_count=number)
            await _clear_state()
            await session.commit()
            await _admin_handler._show_garage_auth_menu(update, context, target_chat_id)
            return
        await CarReviewService.update_setting(session, target_chat_id, reward_points=number)
        await _clear_state()
        await session.commit()
        await _admin_handler._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "teacher_search_delegate_target_input":
        try:
            user = await TeacherSearchService.resolve_delegate_user(session, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await set_user_state(
            session,
            chat_id=target_chat_id,
            user_id=update.effective_user.id,
            state_type="teacher_search_delegate_location_input",
            state_data={"target_chat_id": target_chat_id, "delegate_user_id": user.id},
        )
        await session.commit()
        await update.effective_message.reply_text("👉 请输入经纬度，格式：纬度,经度")
        return

    if state_type == "teacher_search_delegate_location_input":
        parts = [item for item in re.split(r"[\s,，]+", text_value) if item]
        if len(parts) != 2:
            await update.effective_message.reply_text("格式错误，请输入：纬度,经度")
            return
        try:
            latitude = float(parts[0])
            longitude = float(parts[1])
        except ValueError:
            await update.effective_message.reply_text("经纬度格式错误，请重新输入。")
            return
        delegate_user_id = state.state_data.get("delegate_user_id")
        if not isinstance(delegate_user_id, int):
            await _clear_state()
            await session.commit()
            await update.effective_message.reply_text("代录状态异常，请重新进入。")
            return
        await TeacherSearchService.upsert_member_location(
            session,
            chat_id=target_chat_id,
            user_id=delegate_user_id,
            latitude=latitude,
            longitude=longitude,
            operator_user_id=update.effective_user.id,
        )
        await TeacherSearchService.upsert_teacher_profile_from_location(
            session,
            chat_id=target_chat_id,
            user_id=delegate_user_id,
            latitude=latitude,
            longitude=longitude,
        )
        await _clear_state()
        await session.commit()
        await _admin_handler._show_teacher_search_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_submit_command_input":
        if not text_value:
            await update.effective_message.reply_text("指令不能为空。")
            return
        await CarReviewService.update_setting(session, target_chat_id, submit_command=text_value[:64])
        await _clear_state()
        await session.commit()
        await _admin_handler._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_rank_command_input":
        if not text_value:
            await update.effective_message.reply_text("指令不能为空。")
            return
        await CarReviewService.update_setting(session, target_chat_id, rank_command=text_value[:64])
        await _clear_state()
        await session.commit()
        await _admin_handler._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_approver_input":
        approver_id = None
        if text_value != "清空":
            try:
                user = await CarReviewService.resolve_approver(session, text_value)
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
            approver_id = user.id
        await CarReviewService.update_setting(session, target_chat_id, approver_user_id=approver_id)
        await _clear_state()
        await session.commit()
        await _admin_handler._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_template_input":
        if not text_value:
            await update.effective_message.reply_text("模板不能为空。")
            return
        await CarReviewService.update_setting(session, target_chat_id, template_text=message_text)
        await _clear_state()
        await session.commit()
        await _admin_handler._show_car_review_menu(update, context, target_chat_id)
        return

    await update.effective_message.reply_text("配置状态异常，请重新进入页面。")


async def handle_points_extended_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return

    state_type = state.state_type
    text_value = message_text.strip()

    async def _clear_points_state() -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)

    def _parse_state_int(key: str) -> int | None:
        raw = state.state_data.get(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    if state_type in {"custom_points_name_input", "custom_points_rank_input", "custom_points_adjust_input"}:
        type_id = _parse_state_int("type_id")
        if type_id is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("自定义积分状态异常，已自动退出，请重新进入页面。")
            return
        item = await PointsExtendedService.get_custom_point_type(session, target_chat_id, type_id)
        if item is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("自定义积分不存在，请重新进入页面。")
            return
        if state_type == "custom_points_name_input":
            if not text_value:
                await update.effective_message.reply_text("积分名字不能为空。")
                return
            try:
                await PointsExtendedService.update_custom_point_type(session, item, name=text_value[:64])
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        elif state_type == "custom_points_rank_input":
            try:
                await PointsExtendedService.update_custom_point_type(
                    session,
                    item,
                    rank_command=(None if text_value in {"", "清空"} else text_value[:32]),
                )
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        else:
            parts = message_text.strip().split(maxsplit=2)
            if len(parts) < 2 or not re.fullmatch(r"-?\d+", parts[0]) or not re.fullmatch(r"\d+", parts[1]):
                await update.effective_message.reply_text("格式错误，请输入：用户ID 数量 备注(可选)")
                return
            target_user_id = int(parts[0])
            amount = int(parts[1])
            if amount <= 0:
                await update.effective_message.reply_text("数量必须大于 0。")
                return
            mode = state.state_data.get("mode")
            if mode not in {"add", "deduct"}:
                await _clear_points_state()
                await session.commit()
                await update.effective_message.reply_text("自定义积分操作类型异常，已自动退出，请重新进入页面。")
                return
            delta = amount if mode == "add" else -amount
            reason_note = parts[2].strip() if len(parts) >= 3 else None
            await ensure_user(
                session,
                user_id=target_user_id,
                username=None,
                first_name=None,
                last_name=None,
                language_code=None,
            )
            balance = await PointsExtendedService.adjust_custom_points(
                session,
                chat_id=target_chat_id,
                type_id=item.id,
                user_id=target_user_id,
                delta=delta,
                operator_user_id=update.effective_user.id,
                reason_note=reason_note,
            )
            await _clear_points_state()
            await session.commit()
            action_text = "增加" if delta > 0 else "扣除"
            await update.effective_message.reply_text(
                f"已为用户 {target_user_id} {action_text} {abs(delta)} {item.name}，当前余额 {balance}。"
            )
            await _admin_handler._show_custom_point_detail(update, context, target_chat_id, item.id)
            return
        await _clear_points_state()
        await session.commit()
        await _admin_handler._show_custom_point_detail(update, context, target_chat_id, item.id)
        return

    if state_type in {"points_level_name_input", "points_level_threshold_input"}:
        level_id = _parse_state_int("level_id")
        if level_id is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("积分等级状态异常，已自动退出，请重新进入页面。")
            return
        level = await PointsExtendedService.get_level(session, target_chat_id, level_id)
        if level is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("积分等级不存在，请重新进入页面。")
            return
        if state_type == "points_level_name_input":
            if not text_value:
                await update.effective_message.reply_text("等级名称不能为空。")
                return
            try:
                await PointsExtendedService.update_level(session, level, level_name=text_value[:64])
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        else:
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("积分门槛必须是大于 0 的整数。")
                return
            threshold_value = int(text_value)
            if threshold_value <= 0:
                await update.effective_message.reply_text("积分门槛必须大于 0。")
                return
            try:
                await PointsExtendedService.update_level(session, level, point_threshold=threshold_value)
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        await _clear_points_state()
        await session.commit()
        await _admin_handler._show_points_level_detail(update, context, target_chat_id, level.id)
        return

    if state_type == "points_mall_command_input":
        if not text_value:
            await update.effective_message.reply_text("商城指令不能为空。")
            return
        setting = await PointsExtendedService.get_or_create_mall_setting(session, target_chat_id)
        await PointsExtendedService.update_mall_setting(session, setting, entry_command=text_value[:32])
        await _clear_points_state()
        await session.commit()
        await _admin_handler._show_points_mall_menu(update, context, target_chat_id)
        return

    if state_type == "points_mall_cover_input":
        setting = await PointsExtendedService.get_or_create_mall_setting(session, target_chat_id)
        if text_value == "清空":
            await PointsExtendedService.update_mall_setting(
                session,
                setting,
                cover_media_type=None,
                cover_file_id=None,
            )
        else:
            message = update.effective_message
            if message.photo:
                await PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type="photo",
                    cover_file_id=message.photo[-1].file_id,
                )
            elif message.video:
                await PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type="video",
                    cover_file_id=message.video.file_id,
                )
            else:
                await update.effective_message.reply_text("请发送图片或视频，或输入 清空。")
                return
        await _clear_points_state()
        await session.commit()
        await _admin_handler._show_points_mall_cover_placeholder(update, context, target_chat_id)
        return

    if state_type.startswith("points_mall_product_"):
        product_id = _parse_state_int("product_id")
        if product_id is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("商城商品状态异常，已自动退出，请重新进入页面。")
            return
        product = await PointsExtendedService.get_product(session, target_chat_id, product_id)
        if product is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("商城商品不存在，请重新进入页面。")
            return

        if state_type == "points_mall_product_name_input":
            if not text_value:
                await update.effective_message.reply_text("商品名称不能为空。")
                return
            await PointsExtendedService.update_product(session, product, name=text_value[:128])
        elif state_type == "points_mall_product_price_input":
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("所需积分必须是非负整数。")
                return
            price_value = int(text_value)
            if price_value <= 0:
                await update.effective_message.reply_text("所需积分必须大于 0。")
                return
            await PointsExtendedService.update_product(session, product, price_points=price_value)
        elif state_type == "points_mall_product_limit_input":
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("限购次数必须是非负整数。")
                return
            limit_value = int(text_value)
            await PointsExtendedService.update_product(
                session,
                product,
                limit_per_user=(None if limit_value == 0 else limit_value),
            )
        elif state_type == "points_mall_product_stock_input":
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("可售数量必须是非负整数。")
                return
            stock_value = int(text_value)
            await PointsExtendedService.update_product_stock_total(
                session,
                product,
                stock_total=stock_value,
            )
        elif state_type == "points_mall_product_fulfiller_input":
            if text_value == "清空":
                await PointsExtendedService.update_product(session, product, fulfiller_user_id=None)
            else:
                fulfiller_user_id = await PointsExtendedService.resolve_user_id(session, text_value)
                if fulfiller_user_id is None:
                    await update.effective_message.reply_text("未找到该用户，请输入用户ID或已记录的用户名。")
                    return
                if not await PointsExtendedService.is_chat_member(session, target_chat_id, fulfiller_user_id):
                    await update.effective_message.reply_text("发放人员必须是当前群组成员。")
                    return
                await PointsExtendedService.update_product(session, product, fulfiller_user_id=fulfiller_user_id)
        elif state_type == "points_mall_product_description_input":
            await PointsExtendedService.update_product(
                session,
                product,
                description=None if text_value == "清空" else message_text.strip(),
            )
        elif state_type == "points_mall_product_sort_input":
            if not re.fullmatch(r"-?\d+", text_value):
                await update.effective_message.reply_text("排序权重必须是整数。")
                return
            await PointsExtendedService.update_product(session, product, sort_weight=int(text_value))
        elif state_type == "points_mall_product_cover_input":
            if text_value == "清空":
                await PointsExtendedService.update_product(
                    session,
                    product,
                    cover_media_type=None,
                    cover_file_id=None,
                )
            else:
                message = update.effective_message
                if message.photo:
                    await PointsExtendedService.update_product(
                        session,
                        product,
                        cover_media_type="photo",
                        cover_file_id=message.photo[-1].file_id,
                    )
                elif message.video:
                    await PointsExtendedService.update_product(
                        session,
                        product,
                        cover_media_type="video",
                        cover_file_id=message.video.file_id,
                    )
                else:
                    await update.effective_message.reply_text("请发送图片或视频，或输入 清空。")
                    return

        await _clear_points_state()
        await session.commit()
        await _admin_handler._show_points_mall_product_detail(update, context, target_chat_id, product.product_id)
        return

    await update.effective_message.reply_text("当前积分扩展配置状态不支持该输入，请重新进入配置页面。")


async def handle_bottom_button_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("底部按钮状态异常，请重新进入页面。")
        return

    async def _clear_state() -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)

    text_value = message_text.strip()
    state_type = str(state.state_type)

    if state_type == "bottom_button_text_input":
        if not text_value:
            await update.effective_message.reply_text("文本内容不能为空。")
            return
        await update_bottom_button_setting(session, target_chat_id, header_text=text_value)
        await _clear_state()
        await session.commit()
        await _admin_handler._show_bottom_button_menu(update, context, target_chat_id)
        return

    layout_id = state.state_data.get("layout_id")
    if not isinstance(layout_id, int):
        await _clear_state()
        await session.commit()
        await update.effective_message.reply_text("按钮状态异常，请重新进入页面。")
        return

    if state_type == "bottom_button_button_text_input":
        try:
            await update_layout_button(
                session,
                chat_id=target_chat_id,
                layout_id=layout_id,
                button_text=text_value,
            )
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await _clear_state()
        await session.commit()
        await _admin_handler._show_bottom_button_detail(update, context, target_chat_id, layout_id)
        return

    if state_type == "bottom_button_payload_input":
        try:
            await update_layout_button(
                session,
                chat_id=target_chat_id,
                layout_id=layout_id,
                payload_text=text_value,
            )
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await _clear_state()
        await session.commit()
        await _admin_handler._show_bottom_button_detail(update, context, target_chat_id, layout_id)
        return

    await update.effective_message.reply_text("当前底部按钮配置状态不支持该输入，请重新进入配置页面。")


async def handle_game_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("游戏配置状态异常，请重新进入页面。")
        return

    async def _clear_state() -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)

    value = message_text.strip()
    state_type = str(state.state_type)
    try:
        if state_type == "game_wait_rake_ratio":
            await update_game_setting(session, target_chat_id, rake_ratio=parse_game_ratio(value))
        elif state_type == "game_wait_rake_owner":
            await update_game_setting(session, target_chat_id, rake_owner_user_id=await resolve_game_rake_owner(session, value))
        elif state_type == "game_wait_auto_start_time":
            await update_game_setting(session, target_chat_id, auto_start_time=validate_game_hhmm(value))
        elif state_type == "game_wait_auto_stop_time":
            await update_game_setting(session, target_chat_id, auto_stop_time=validate_game_hhmm(value))
        else:
            await update.effective_message.reply_text("当前游戏配置状态不支持该输入，请重新进入配置页面。")
            return
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await _clear_state()
    await session.commit()
    await _admin_handler._show_game_menu(update, context, target_chat_id)


async def handle_guess_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("竞猜配置状态异常，请重新进入页面。")
        return

    state_type = str(state.state_type)
    draft = dict(state.state_data or {})
    value = message_text.strip()

    async def _save_draft(next_type: str = "guess_wait_title") -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await set_user_state(
            session,
            chat_id=update.effective_user.id,
            user_id=update.effective_user.id,
            state_type=next_type,
            state_data=draft,
        )

    if state_type == "guess_wait_rake_ratio":
        try:
            await update_guess_setting(session, target_chat_id, rake_ratio=parse_guess_ratio(value))
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await session.commit()
        await _admin_handler._show_guess_settings(update, context, target_chat_id)
        return

    if state_type == "guess_wait_rake_owner":
        try:
            await update_guess_setting(session, target_chat_id, rake_owner_user_id=await resolve_guess_user_id(session, value))
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await session.commit()
        await _admin_handler._show_guess_settings(update, context, target_chat_id)
        return

    try:
        if state_type == "guess_wait_title":
            if not value:
                await update.effective_message.reply_text("活动名字不能为空。")
                return
            draft["title"] = value[:128]
        elif state_type == "guess_wait_cover":
            if value == "清空":
                draft["cover_file_id"] = None
            elif update.effective_message.photo:
                draft["cover_file_id"] = update.effective_message.photo[-1].file_id
            else:
                await update.effective_message.reply_text("请发送图片，或发送“清空”。")
                return
        elif state_type == "guess_wait_description":
            draft["description"] = value
        elif state_type == "guess_wait_banker":
            banker_user_id = await resolve_guess_user_id(session, value)
            draft["banker_user_id"] = banker_user_id
            draft["mode"] = "banker" if banker_user_id else "no_banker"
        elif state_type == "guess_wait_pool":
            if not re.fullmatch(r"\d+", value):
                await update.effective_message.reply_text("公共奖池必须是非负整数。")
                return
            draft["public_pool"] = int(value)
        elif state_type == "guess_wait_options":
            draft["options"] = parse_guess_options(value)
        elif state_type == "guess_wait_command":
            if not value:
                await update.effective_message.reply_text("群内指令不能为空。")
                return
            draft["command_keyword"] = value[:32]
        elif state_type == "guess_wait_deadline":
            draft["deadline_at"] = parse_guess_deadline(value).isoformat()
        else:
            await update.effective_message.reply_text("当前竞猜配置状态不支持该输入，请重新进入配置页面。")
            return
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await _save_draft()
    await session.commit()
    await _admin_handler._show_guess_create_menu(update, context, target_chat_id, draft)


async def handle_engagement_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("促活工具配置状态异常，请重新进入页面。")
        return

    async def _clear_state() -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)

    state_type = str(state.state_type)
    value = message_text.strip()

    try:
        if state_type == "engagement_wait_egg_template":
            event = await update_egg_event_from_template(
                session,
                target_chat_id,
                value,
                event_id=state.state_data.get("event_id"),
            )
            await _clear_state()
            await session.commit()
            await _admin_handler._show_engagement_egg(update, context, target_chat_id, event.id)
            return
        if state_type == "engagement_wait_chat_target":
            if not re.fullmatch(r"\d+", value):
                await update.effective_message.reply_text("发言达标数量必须是正整数。")
                return
            await update_engagement_chat_reward(session, target_chat_id, daily_message_target=max(int(value), 1))
            await _clear_state()
            await session.commit()
            await _admin_handler._show_engagement_chat_reward(update, context, target_chat_id)
            return
        if state_type == "engagement_wait_chat_plan":
            await update_engagement_chat_reward(session, target_chat_id, reward_points_plan=parse_engagement_reward_plan(value))
            await _clear_state()
            await session.commit()
            await _admin_handler._show_engagement_chat_reward(update, context, target_chat_id)
            return
        if state_type == "engagement_wait_chat_command":
            if not value:
                await update.effective_message.reply_text("领奖口令不能为空。")
                return
            await update_engagement_chat_reward(session, target_chat_id, command_keyword=value[:32])
            await _clear_state()
            await session.commit()
            await _admin_handler._show_engagement_chat_reward(update, context, target_chat_id)
            return
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await update.effective_message.reply_text("当前促活工具配置状态不支持该输入，请重新进入配置页面。")


def _get_action_label(action: str) -> str:
    """获取惩罚动作标签"""
    labels = {
        "delete": "删除消息",
        "mute": "禁言",
        "ban": "封禁",
    }
    return labels.get(action, action)


def _normalize_mall_order_status(raw_status: str) -> str:
    normalized = (raw_status or "").strip().lower()
    mapping = {
        "a": "all",
        "c": "created",
        "f": "fulfilled",
        "x": "canceled",
        "r": "refunded",
        "all": "all",
        "created": "created",
        "fulfilled": "fulfilled",
        "canceled": "canceled",
        "refunded": "refunded",
    }
    return mapping.get(normalized, "all")


def _normalize_car_review_report_status(raw_status: str) -> str:
    normalized = (raw_status or "").strip().lower()
    mapping = {
        "0": "all",
        "p": "pending",
        "a": "approved",
        "u": "published",
        "r": "rejected",
        "all": "all",
        "pending": "pending",
        "approved": "approved",
        "published": "published",
        "rejected": "rejected",
    }
    return mapping.get(normalized, "all")


def _car_review_report_status_code(status: str) -> str:
    mapping = {
        "all": "0",
        "pending": "p",
        "approved": "a",
        "published": "u",
        "rejected": "r",
    }
    return mapping.get((status or "").strip().lower(), "0")


def _normalize_gfw_audit_result(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    mapping = {
        "a": "all",
        "s": "success",
        "k": "skipped",
        "f": "failed",
        "all": "all",
        "success": "success",
        "skipped": "skipped",
        "failed": "failed",
    }
    return mapping.get(normalized, "all")


def _gfw_audit_result_code(result: str) -> str:
    mapping = {
        "all": "a",
        "success": "s",
        "skipped": "k",
        "failed": "f",
    }
    return mapping.get((result or "").strip().lower(), "a")


def _garage_forward_mode_label(mode: str) -> str:
    labels = {
        "all": "全部",
        "text": "仅文本",
        "media": "仅媒体",
        "keyword": "关键词",
    }
    return labels.get((mode or "all").strip().lower(), "全部")
