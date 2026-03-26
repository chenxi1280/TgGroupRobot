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
from bot.services.base import ValidationError
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.state.state_service import set_user_state, clear_user_state
from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import answer_callback_query_safely, build_public_error_text, mark_callback_query_answered


log = structlog.get_logger(__name__)


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
        if action in {"delete_mode", "delegate"}:
            return cb.get_int_optional(2)
        if action == "open_course":
            return cb.get_int_optional(3)
        return None

    if prefix == "crv":
        action = cb.get(1)
        if action == "home":
            return cb.get_int_optional(2)
        if action in {"toggle", "mode", "lookup", "publish_target", "approver", "template", "reward", "submit_cmd", "rank_cmd"}:
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
                        [InlineKeyboardButton("返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")],
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
                        [InlineKeyboardButton("返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")],
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
            await self.message_helper.safe_edit(update, text=prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")]]))
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
                    [[InlineKeyboardButton("返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")]]
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
            await self.message_helper.safe_edit(update, text=prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"adm:lvl:{chat_id}:detail:{level_id}")]]))
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
            await self._show_points_mall_orders_placeholder(update, context, chat_id, product_id=product_id)
            return
        if op == "order":
            sub = callback_data.get(4)
            order_id = callback_data.get_int(5)
            if sub == "detail":
                await self._show_points_mall_order_detail(update, context, chat_id, order_id)
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
            await self._show_points_mall_order_detail(update, context, chat_id, order_id)
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
                            [InlineKeyboardButton("返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")],
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
                            [[InlineKeyboardButton("返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
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
                        [[InlineKeyboardButton("返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
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
        from bot.services.activity.lottery_service import get_lottery_stats

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            stats = await get_lottery_stats(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = f"🎁[{chat_title}]抽奖\n\n"
        text += f"创建的抽奖次数:{stats['total']}\n\n"
        text += f"已开奖:{stats['completed']}       未开奖:{stats['pending']}       取消:{stats['cancelled']}"

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
        from bot.keyboards.integration.invite_link import invite_link_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "🔗 邀请链接管理\n\n请选择操作："
        keyboard = invite_link_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

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
        """显示广告管理菜单"""
        from bot.keyboards.content.ads import ads_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "📢 广告管理\n\n请选择操作："
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

        text = "⚙️控制权限\n\n你可以制定哪些管理员能够设置机器人"
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
                InlineKeyboardButton("⚙️ 话术开关", callback_data=f"adm:menu:closegroup:{chat_id}"),
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
                InlineKeyboardButton("⚙️ 定时开关", callback_data=f"adm:menu:closegroup:{chat_id}"),
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
                InlineKeyboardButton("🧹 删除提示消息", callback_data=f"adm:menu:renamewatch:{chat_id}"),
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
        text = (
            "📣 强制订阅频道\n\n"
            "新用户需要订阅指定的频道，没订阅将无法发言。\n\n"
            f"状态: {'✅ 启动' if enabled else '❌ 关闭'}\n"
            f"绑定频道1: {ch1}\n"
            f"绑定频道2: {ch2}\n"
            f"设置封面: {'已设置' if cover_set else '未设置'}\n"
            f"自定义按钮: {'✅启用' if custom_buttons else '跟随频道按钮'}（{button_summary}）\n"
            "没订阅时处理: 删除消息并提示订阅\n"
            f"删除提示消息: {delete_after}秒后删除\n\n"
            f"当前文案:\n{guide_text}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态", callback_data=f"adm:fs:{chat_id}:toggle:enabled"),
                InlineKeyboardButton("✅ 启动" if enabled else "❌ 关闭", callback_data=f"adm:fs:{chat_id}:toggle:enabled"),
            ],
            [
                InlineKeyboardButton("⚙️ 绑定频道1", callback_data=f"adm:fs:{chat_id}:input:channel1"),
                InlineKeyboardButton(ch1[:16], callback_data=f"adm:fs:{chat_id}:input:channel1"),
            ],
            [
                InlineKeyboardButton("⚙️ 绑定频道2", callback_data=f"adm:fs:{chat_id}:input:channel2"),
                InlineKeyboardButton(ch2[:16], callback_data=f"adm:fs:{chat_id}:input:channel2"),
            ],
            [
                InlineKeyboardButton("🖼️ 设置封面", callback_data=f"adm:fs:{chat_id}:input:cover"),
                InlineKeyboardButton("📝 设置文案", callback_data=f"adm:fs:{chat_id}:input:text"),
            ],
            [
                InlineKeyboardButton("⌨️ 自定义按钮", callback_data=f"adm:fs:{chat_id}:toggle:buttons"),
                InlineKeyboardButton(button_summary, callback_data=f"adm:fs:{chat_id}:input:buttons"),
            ],
            [
                InlineKeyboardButton("⚙️ 删除提示消息", callback_data=f"adm:fs:{chat_id}:delete_after:60"),
                InlineKeyboardButton(f"{delete_after}秒后删除", callback_data=f"adm:fs:{chat_id}:cycle_delete_after"),
            ],
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
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("状态：", callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
                InlineKeyboardButton("启用" if item.enabled else "关闭", callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("模式：", callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
                InlineKeyboardButton(mode_label, callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
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
            [InlineKeyboardButton("❌ 删除配置", callback_data=f"adm:wel:{chat_id}:delete:{welcome_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:welcome:{chat_id}")],
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
            await session.commit()

        if alliance is None:
            text = (
                "🖐 联盟功能\n\n"
                "群组可以组建自己的联盟，在同一联盟中的群组，可以实现同步封禁等共享能力。"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("创建联盟", callback_data=f"ali:create:input:{chat_id}")],
                [InlineKeyboardButton("加入联盟", callback_data=f"ali:join:input:{chat_id}")],
                [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
            ])
            await self.message_helper.safe_edit(update, text, reply_markup=keyboard)
            return

        joint_ban_enabled = bool(setting.joint_ban_enabled) if setting is not None else False
        is_owner = alliance.owner_chat_id == chat_id
        text = (
            "🖐 联盟功能\n\n"
            f"🟩 联盟名字：{alliance.name}\n\n"
            "🚫 联合封禁\n"
            "└ 联盟群使用 t 指令封禁用户，该用户加入联合封禁列表\n"
            "└ 联合封禁列表中的用户，在联盟其他群中发言，会被自动封禁\n\n"
            f"邀请码权限：{'创建群可重置' if is_owner else '仅创建群可重置'}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💥 查看联盟成员", callback_data=f"ali:members:{chat_id}")],
            [
                InlineKeyboardButton("联合封禁", callback_data=f"ali:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if joint_ban_enabled else "启动", callback_data=f"ali:jointban:toggle:{chat_id}:1"),
                InlineKeyboardButton("✅ 关闭" if not joint_ban_enabled else "关闭", callback_data=f"ali:jointban:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton(
                    "🔑 邀请密码" if is_owner else "🔑 邀请密码（仅创建群）",
                    callback_data=f"ali:invite:show:{chat_id}" if is_owner else f"ali:invite:denied:{chat_id}",
                ),
                InlineKeyboardButton("🚪 退出联盟", callback_data=f"ali:leave:{chat_id}:confirm"),
            ],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"ali:home:{chat_id}")]])
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
                InlineKeyboardButton("状态", callback_data=f"gfw:home:{chat_id}"),
                InlineKeyboardButton("启动", callback_data=f"gfw:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"gfw:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("模式", callback_data=f"gfw:home:{chat_id}"),
                InlineKeyboardButton("全部", callback_data=f"gfw:mode:{chat_id}:all"),
                InlineKeyboardButton("仅文本", callback_data=f"gfw:mode:{chat_id}:text"),
            ],
            [
                InlineKeyboardButton("仅媒体", callback_data=f"gfw:mode:{chat_id}:media"),
                InlineKeyboardButton("关键词", callback_data=f"gfw:mode:{chat_id}:keyword"),
            ],
            [InlineKeyboardButton("✏️ 关键词规则", callback_data=f"gfw:keywords:input:{chat_id}")],
            [InlineKeyboardButton("➕ 添加来源频道", callback_data=f"gfw:source:add:{chat_id}")],
        ]
        for item in sources[:10]:
            keyboard_rows.append(
                [InlineKeyboardButton(f"🗑 移除 {item.source_name or item.source_channel_id}", callback_data=f"gfw:source:remove:{chat_id}:{item.id}")]
            )
        keyboard_rows.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")])
        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

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
                InlineKeyboardButton("状态：", callback_data=f"grg:home:{chat_id}"),
                InlineKeyboardButton("启动", callback_data=f"grg:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"grg:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 认证图标", callback_data=f"grg:badge:{chat_id}"),
                InlineKeyboardButton("🤝", callback_data=f"grg:badge:{chat_id}"),
            ],
            [InlineKeyboardButton("💌 手动认证老师", callback_data=f"grg:teacher:list:{chat_id}:0")],
            [InlineKeyboardButton("🧾 生成老师汇总信息", callback_data=f"grg:summary:gen:{chat_id}")],
            [
                InlineKeyboardButton("限制发言", callback_data=f"grg:home:{chat_id}"),
                InlineKeyboardButton("开启", callback_data=f"grg:limit:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"grg:limit:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("图", callback_data=f"grg:limit:mode:{chat_id}:image"),
                InlineKeyboardButton("文+图", callback_data=f"grg:limit:mode:{chat_id}:image_text"),
                InlineKeyboardButton("关闭", callback_data=f"grg:limit:mode:{chat_id}:none"),
            ],
            [
                InlineKeyboardButton(f"时间间隔（{settings.garage_limit_interval_sec // 3600}小时）", callback_data=f"grg:limit:interval:{chat_id}"),
                InlineKeyboardButton(f"限制条数（{settings.garage_limit_max_count}条）", callback_data=f"grg:limit:max:{chat_id}"),
            ],
            [InlineKeyboardButton("📄 限制发言白名单", callback_data=f"grg:wl:list:{chat_id}:0")],
            [
                InlineKeyboardButton("地区", callback_data=f"grg:summary:partition:{chat_id}:region"),
                InlineKeyboardButton("价格", callback_data=f"grg:summary:partition:{chat_id}:price"),
            ],
            [
                InlineKeyboardButton("只显开课：开", callback_data=f"grg:summary:open:{chat_id}:1"),
                InlineKeyboardButton("只显开课：关", callback_data=f"grg:summary:open:{chat_id}:0"),
            ],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
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
        keyboard_rows.append([InlineKeyboardButton("返回", callback_data=f"grg:home:{chat_id}")])
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
        keyboard_rows.append([InlineKeyboardButton("返回", callback_data=f"grg:home:{chat_id}")])
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

        delete_label = "不删除" if setting.delete_mode == "none" else "删除"
        footer_label = setting.footer_button_label or "无"
        text = (
            "🔎 老师搜索\n\n"
            "根据车库频道信息提供群内搜索功能，需要提前找天行者进行车库对接。\n\n"
            "标签搜索：输入车牌名称、地址、服务等信息\n"
            "附近搜索：群友发送附近可查询周边老师\n"
            "开课打卡：当日发言老师可视为开课\n"
            "强制录入：未录入位置可限制功能使用\n\n"
            f"标签搜索：{'✅ 启动' if setting.tag_search_enabled else '❌ 关闭'}\n"
            f"开课打卡：{'✅ 启动' if setting.attendance_enabled else '❌ 关闭'}\n"
            f"附近搜索：{'✅ 启动' if setting.nearby_search_enabled else '❌ 关闭'}\n"
            f"底部按钮：{footer_label}\n"
            f"删除消息：{delete_label}\n"
            f"开课老师：{len(open_teachers)} 人"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("标签搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动", callback_data=f"tsearch:toggle:tag:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"tsearch:toggle:tag:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("开课打卡：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动", callback_data=f"tsearch:toggle:attendance:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"tsearch:toggle:attendance:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("附近搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动", callback_data=f"tsearch:toggle:nearby:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"tsearch:toggle:nearby:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("强制录入：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动", callback_data=f"tsearch:toggle:force_loc:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"tsearch:toggle:force_loc:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("底部按钮", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(footer_label, callback_data=f"tsearch:home:{chat_id}"),
            ],
            [
                InlineKeyboardButton("删除消息：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(delete_label, callback_data=f"tsearch:delete_mode:{chat_id}:{'delete' if setting.delete_mode == 'none' else 'none'}"),
            ],
            [InlineKeyboardButton("📍 代录老师位置", callback_data=f"tsearch:delegate:start:{chat_id}")],
            [InlineKeyboardButton("📚 开课老师", callback_data=f"tsearch:open_course:list:{chat_id}:0")],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
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
            approver = await session.get(TgUser, setting.approver_user_id) if setting.approver_user_id else None
            await session.commit()

        mode_label = "默认" if setting.review_mode == "default" else "简易"
        lookup_label = {"exact": "精准", "contains": "包含", "off": "关闭"}.get(setting.teacher_lookup_mode, setting.teacher_lookup_mode)
        approver_label = f"@{approver.username}" if approver and approver.username else ("未指定" if not setting.approver_user_id else str(setting.approver_user_id))
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
            f"自定义项：{len(fields)} 项"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 开关", callback_data=f"crv:home:{chat_id}"),
                InlineKeyboardButton("启动", callback_data=f"crv:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭", callback_data=f"crv:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 模式", callback_data=f"crv:home:{chat_id}"),
                InlineKeyboardButton("✅ 默认", callback_data=f"crv:mode:{chat_id}:default"),
                InlineKeyboardButton("简易", callback_data=f"crv:mode:{chat_id}:simple"),
            ],
            [
                InlineKeyboardButton("⚙️ 查车评", callback_data=f"crv:home:{chat_id}"),
                InlineKeyboardButton("精准", callback_data=f"crv:lookup:{chat_id}:exact"),
                InlineKeyboardButton("包含", callback_data=f"crv:lookup:{chat_id}:contains"),
            ],
            [InlineKeyboardButton("🚫 关闭查车评", callback_data=f"crv:lookup:{chat_id}:off")],
            [InlineKeyboardButton("💬 提交评价指令", callback_data=f"crv:submit_cmd:edit:{chat_id}")],
            [InlineKeyboardButton("🥇 查询排行指令", callback_data=f"crv:rank_cmd:edit:{chat_id}")],
            [InlineKeyboardButton("📤 报告发布", callback_data=f"crv:publish_target:{chat_id}:menu")],
            [InlineKeyboardButton(f"🪙 积分奖励：加 {setting.reward_points} 积分", callback_data=f"crv:reward:{chat_id}")],
            [InlineKeyboardButton(f"🕵️ 审核人员：{approver_label}", callback_data=f"crv:approver:set:{chat_id}")],
            [InlineKeyboardButton("✏️ 自定义项", callback_data=f"crv:home:{chat_id}")],
            [InlineKeyboardButton("📝 报告模版", callback_data=f"crv:template:edit:{chat_id}")],
            [InlineKeyboardButton("📂 评价管理", callback_data=f"crv:home:{chat_id}")],
            [InlineKeyboardButton("👩 在榜老师", callback_data=f"tsearch:open_course:list:{chat_id}:0")],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

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
                InlineKeyboardButton("带图发送：开启", callback_data=f"crv:home:{chat_id}"),
                InlineKeyboardButton("❌ 关闭", callback_data=f"crv:home:{chat_id}"),
            ],
            [InlineKeyboardButton(("✅ " if setting.publish_to_main_group else "") + "直接发到主群", callback_data=f"crv:publish_target:{chat_id}:main")],
            [InlineKeyboardButton(("✅ " if setting.publish_to_comment_group else "") + "评论车库帖子", callback_data=f"crv:publish_target:{chat_id}:comment")],
            [InlineKeyboardButton(("✅ " if setting.publish_to_bound_channel else "") + "发送指定频道", callback_data=f"crv:publish_target:{chat_id}:channel")],
            [InlineKeyboardButton("返回", callback_data=f"crv:home:{chat_id}")],
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
        from bot.models.enums import ConversationStateType

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
                "buttons": "👉 请输入按钮 JSON，例如 [[{\"text\":\"加入频道\",\"url\":\"https://t.me/example\"}]]；发送“清空”可移除按钮。",
            }[arg]
            await self.message_helper.safe_edit(
                update,
                prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:forcesub:{chat_id}")]]),
            )
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"ali:home:{chat_id}")]]),
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"ali:home:{chat_id}")]]),
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"gfw:home:{chat_id}")]]),
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"gfw:home:{chat_id}")]]),
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"grg:home:{chat_id}")]]),
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
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"grg:teacher:list:{chat_id}:0")]]),
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
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"grg:home:{chat_id}")]]),
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
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"grg:wl:list:{chat_id}:0")]]),
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
                await answer_callback_query_safely(update, "老师汇总功能已接通配置，生成内容将在后续消息链路里使用。", show_alert=True)
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"tsearch:home:{chat_id}")]]),
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"tsearch:home:{chat_id}")]]),
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
            await self.message_helper.safe_edit(update, "💯 车评系统 | 提交报告指令\n\n👉 请输入新的指令：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "rank_cmd" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_rank_command_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 查询排行指令\n\n👉 请输入新的指令：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"crv:home:{chat_id}")]]))
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
            await self.message_helper.safe_edit(update, "💯 车评系统 | 指定审核人\n\n👉 请输入用户名或ID，发送“清空”取消：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "template" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_template_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 评价模板\n\n👉 请输入新的模板：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "reward":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_reward_points_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 积分奖励\n\n👉 请输入奖励积分：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"crv:home:{chat_id}")]]))
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

        # 格式化当前配置
        mode_label = {
            "button": "按钮验证",
            "math": "数学题",
            "captcha": "验证码",
            "admin": "管理员确认",
        }.get(settings.verification_mode, settings.verification_mode)

        action_label = "禁言" if settings.verification_timeout_action == "mute" else "踢出"
        status_label = "✅ 开启" if settings.verification_enabled else "❌ 关闭"

        text = f"🤖 [{chat_title}] 新人验证\n\n"
        text += f"状态: {status_label}\n"
        text += f"验证方式: {mode_label}\n"
        text += f"超时时间: {settings.verification_timeout_seconds} 秒\n"
        text += f"超时处理: {action_label}\n"
        if settings.verification_timeout_action == "mute":
            text += f"禁言时长: {settings.verification_mute_duration} 秒\n"
        text += f"限制发言: {'是' if settings.verification_restrict_can_send else '否'}\n\n"
        text += f"💡 点击下方按钮修改配置"

        # 创建配置按钮
        buttons = [
            [InlineKeyboardButton("📝 修改配置", callback_data=f"adm:vfy_config:{chat_id}")],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        log.info("=== CALLING SAFE_EDIT FOR VERIFICATION MENU ===")
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
        log.info("=== SAFE_EDIT COMPLETED ===")

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
        text = f"💰 [{chat_title}] 积分配置\n\n"
        text += f"请选择要修改的项目："

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
            lines.append("0 条数据，第 1 页/共 0 页")

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
        total_pages = 1 if levels else 0
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
            reply_markup=points_mall_orders_keyboard(chat_id),
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
            text = "🛍️ 管理商品 | 商品列表\n\n0 条数据，第 1 页/共 0 页"
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
    ) -> None:
        """显示积分商城订单管理页"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            orders = await PointsExtendedService.list_recent_orders(
                session,
                chat_id,
                limit=20,
                product_id=product_id,
            )
            await session.commit()
        if orders:
            title = "🧾 管理订单" if product_id is None else f"🧾 管理订单 | 商品 {product_id}"
            lines = [title, ""]
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
                "🧾 管理订单\n\n0 条数据，第 1 页/共 0 页"
                if product_id is None
                else f"🧾 管理订单 | 商品 {product_id}\n\n0 条数据，第 1 页/共 0 页"
            )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_orders_keyboard(chat_id, orders=orders, product_id=product_id),
        )

    async def _show_points_mall_order_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        order_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            order = await PointsExtendedService.get_order(session, chat_id, order_id)
            await session.commit()
        if order is None:
            await answer_callback_query_safely(update, "订单不存在", show_alert=True)
            await self._show_points_mall_orders_placeholder(update, context, chat_id)
            return
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
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_order_detail_keyboard(chat_id, order),
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
                    [InlineKeyboardButton("返回", callback_data=f"adm:lvl:{chat_id}:detail:{level_id}")],
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
                [[InlineKeyboardButton("返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
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

        text = "🧹 删除系统提示\n\n"
        text += "本功能会自动清除系统提示消息"

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
        if cb.get(0) in {"adm", "ali", "gfw", "grg", "tsearch", "crv"}:
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
        setattr(settings, field, message_text.strip())
    elif state.state_type == "force_subscribe_channel_2_input":
        field = "force_subscribe_bound_channel_2"
        setattr(settings, field, message_text.strip())
    elif state.state_type == "force_subscribe_text_input":
        field = "force_subscribe_guide_text"
        setattr(settings, field, message_text.strip())
    elif state.state_type == "force_subscribe_buttons_input":
        if message_text.strip() == "清空":
            settings.force_subscribe_buttons = []
            settings.force_subscribe_custom_buttons_enabled = False
        else:
            try:
                buttons = json.loads(message_text)
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


def _get_action_label(action: str) -> str:
    """获取惩罚动作标签"""
    labels = {
        "delete": "删除消息",
        "mute": "禁言",
        "ban": "封禁",
    }
    return labels.get(action, action)


def _garage_forward_mode_label(mode: str) -> str:
    labels = {
        "all": "全部",
        "text": "仅文本",
        "media": "仅媒体",
        "keyword": "关键词",
    }
    return labels.get((mode or "all").strip().lower(), "全部")
