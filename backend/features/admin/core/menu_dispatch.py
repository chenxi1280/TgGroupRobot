from __future__ import annotations

from backend.features.admin.support import *


ADMIN_MENU_HANDLERS = {
    "main": "_show_main_menu",
    "settings": "_show_settings_menu",
    "lottery": "_show_lottery_menu",
    "solitaire": "_show_solitaire_menu",
    "invite": "_show_invite_menu",
    "autoreply": "_show_autoreply_menu",
    "keywords": "_show_keywords_menu",
    "punish": "_show_punishment_policy_menu",
    "scheduled": "_show_scheduled_menu",
    "ads": "_show_ads_menu",
    "verification": "_show_verification_menu",
    "points": "_show_points_menu",
    "stats": "_show_stats_menu",
    "autodel": "_show_auto_delete_menu",
    "flood": "_show_anti_flood_menu",
    "antispam": "_show_antispam_menu",
    "renewal": "_show_renewal_menu",
    "health": "_show_health_menu",
    "control": "_show_control_permission_menu",
    "closegroup": "_show_group_lock_menu",
    "renamewatch": "_show_rename_monitor_menu",
    "forcesub": "_show_force_subscribe_menu",
    "newmem": "_show_new_member_limit_menu",
    "night": "_show_night_mode_menu",
    "gcmd": "_show_command_config_menu",
    "import": "_show_import_settings_menu",
    "clone": "_show_clone_settings_menu",
    "welcome": "_show_welcome_list_menu",
    "alliance": "_show_alliance_menu",
    "garage_forward": "_show_garage_forward_prompt",
    "sync": "_show_garage_forward_prompt",
    "garage_auth": "_show_garage_auth_menu",
    "teacher_search": "_show_teacher_search_menu",
    "car_review": "_show_car_review_menu",
    "custom_points": "_show_custom_points_menu",
    "custom_points_add": "_show_custom_points_add_entry",
    "points_level": "_show_points_level_menu",
    "points_level_add": "_show_points_level_add_entry",
    "points_mall": "_show_points_mall_menu",
    "points_mall_cover": "_show_points_mall_cover_page",
    "points_mall_command": "_show_points_mall_command_page",
    "points_mall_products": "_show_points_mall_products_page",
    "points_mall_orders": "_show_points_mall_orders_page",
    "auction": "_show_auction_menu",
    "bottom_button": "_show_bottom_button_menu",
    "game": "_show_game_menu",
    "guess": "_show_guess_home",
    "engagement": "_show_engagement_home",
    "inherit": "_show_account_inherit_menu",
    "qpub": "_show_quick_publish_menu",
}


class CoreMenuDispatchMixin:
    async def _handle_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        """处理菜单操作"""
        menu_action = callback_data.get(2)

        handler_name = ADMIN_MENU_HANDLERS.get(menu_action)
        if handler_name is None:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data=f"adm:menu:main:{chat_id}")],
            ])
            await self.message_helper.safe_edit(
                update,
                text="⚠️ 菜单入口已失效，请返回主菜单重新进入。",
                reply_markup=keyboard,
            )
            return

        handler = getattr(self, handler_name)
        await handler(update, context, chat_id)

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
            ("⚠️ 入口已失效", "该入口已失效，请返回主菜单重新进入。"),
        )
        text = "\n".join(
            [
                feature_name,
                "",
                feature_desc,
                "",
                "如需该功能，请从主菜单重新进入。",
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
