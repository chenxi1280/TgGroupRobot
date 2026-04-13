from __future__ import annotations

from backend.features.admin.support import *


class CoreAdminControllerMixin:
    async def _build_import_source_keyboard(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        target_chat_id: int,
        mode: str,
    ) -> InlineKeyboardMarkup:
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        rows: list[list[InlineKeyboardButton]] = []
        for chat_id, title, _ in chats:
            if mode == "import":
                label = f"{title}"
                rows.append([InlineKeyboardButton(label, callback_data=f"adm:import:{target_chat_id}:source:{chat_id}")])
            else:
                if chat_id == target_chat_id:
                    continue
                label = f"{title}"
                rows.append([InlineKeyboardButton(label, callback_data=f"adm:clone:{target_chat_id}:target:{chat_id}")])
        rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{mode}:{target_chat_id}")])
        return InlineKeyboardMarkup(rows)

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
            "health": self._show_health_menu,
            "control": self._show_control_permission_menu,
            "closegroup": self._show_group_lock_menu,
            "renamewatch": self._show_rename_monitor_menu,
            "forcesub": self._show_force_subscribe_menu,
            "newmem": self._show_new_member_limit_menu,
            "night": self._show_night_mode_menu,
            "gcmd": self._show_command_config_menu,
            "import": self._show_import_settings_menu,
            "clone": self._show_clone_settings_menu,
            "welcome": self._show_welcome_list_menu,
            "alliance": self._show_alliance_menu,
            "garage_forward": self._show_garage_forward_prompt,
            "sync": self._show_garage_forward_prompt,
            "garage_auth": self._show_garage_auth_menu,
            "teacher_search": self._show_teacher_search_menu,
            "car_review": self._show_car_review_menu,
            "custom_points": self._show_custom_points_menu,
            "custom_points_add": self._show_custom_points_add_entry,
            "points_level": self._show_points_level_menu,
            "points_level_add": self._show_points_level_add_entry,
            "points_mall": self._show_points_mall_menu,
            "points_mall_cover": self._show_points_mall_cover_page,
            "points_mall_command": self._show_points_mall_command_page,
            "points_mall_products": self._show_points_mall_products_page,
            "points_mall_orders": self._show_points_mall_orders_page,
            "auction": self._show_auction_menu,
            "bottom_button": self._show_bottom_button_menu,
            "game": self._show_game_menu,
            "guess": self._show_guess_home,
            "engagement": self._show_engagement_home,
            "inherit": self._show_account_inherit_menu,
            "qpub": self._show_quick_publish_menu,
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

    async def _get_chat_title(self, db: Database, chat_id: int) -> str:
        """获取群组标题（优先从 Telegram API 实时获取）"""
        from backend.platform.db.schema.models.core import TgChat
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
        from backend.features.activity.ui.lottery import lottery_menu_keyboard
        from backend.features.activity.services.lottery_service import count_lotteries_by_type, get_lottery_stats

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
        from backend.features.activity.ui.solitaire import solitaire_menu_keyboard

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
        from backend.features.invite.invite_link_handler import _invite_link_handler

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
        from backend.features.moderation.ui.auto_reply import auto_reply_menu_keyboard

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
        from backend.features.moderation.ui.banned_word import banned_word_menu_keyboard

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
        from backend.features.automation.scheduled_message_handler import _scheduled_message_handler

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
        from backend.features.automation.ui.ads import ads_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "🎠 轮播广告\n\n请选择操作："
        keyboard = ads_menu_keyboard(chat_id)

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

