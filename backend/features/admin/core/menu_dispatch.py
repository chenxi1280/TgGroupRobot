from __future__ import annotations

from backend.shared.callback_parser import CallbackData

from backend.features.admin.support import *
_HANDLE_TOGGLE_THRESHOLD_4 = 4



ADMIN_MENU_HANDLERS = {
    "main": "_show_main_menu",
    "category_safety": "_show_category_safety",
    "category_messages": "_show_category_messages",
    "category_growth": "_show_category_growth",
    "category_activities": "_show_category_activities",
    "category_garage": "_show_category_garage",
    "category_system": "_show_category_system",

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
    "closegroup": "_show_night_mode_menu",
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
    def _menu_dispatch(self):
        return {
            'main': self._show_main_menu,
            'category_safety': self._show_category_safety,
            'category_messages': self._show_category_messages,
            'category_growth': self._show_category_growth,
            'category_activities': self._show_category_activities,
            'category_garage': self._show_category_garage,
            'category_system': self._show_category_system,
            'settings': self._show_settings_menu,
            'lottery': self._show_lottery_menu,
            'solitaire': self._show_solitaire_menu,
            'invite': self._show_invite_menu,
            'autoreply': self._show_autoreply_menu,
            'keywords': self._show_keywords_menu,
            'punish': self._show_punishment_policy_menu,
            'scheduled': self._show_scheduled_menu,
            'ads': self._show_ads_menu,
            'verification': self._show_verification_menu,
            'points': self._show_points_menu,
            'stats': self._show_stats_menu,
            'autodel': self._show_auto_delete_menu,
            'flood': self._show_anti_flood_menu,
            'antispam': self._show_antispam_menu,
            'renewal': self._show_renewal_menu,
            'health': self._show_health_menu,
            'control': self._show_control_permission_menu,
            'closegroup': self._show_night_mode_menu,
            'renamewatch': self._show_rename_monitor_menu,
            'forcesub': self._show_force_subscribe_menu,
            'newmem': self._show_new_member_limit_menu,
            'night': self._show_night_mode_menu,
            'gcmd': self._show_command_config_menu,
            'import': self._show_import_settings_menu,
            'clone': self._show_clone_settings_menu,
            'welcome': self._show_welcome_list_menu,
            'alliance': self._show_alliance_menu,
            'garage_forward': self._show_garage_forward_prompt,
            'sync': self._show_garage_forward_prompt,
            'garage_auth': self._show_garage_auth_menu,
            'teacher_search': self._show_teacher_search_menu,
            'car_review': self._show_car_review_menu,
            **self._business_menu_dispatch(),
        }

    def _business_menu_dispatch(self):
        return {
            'custom_points': self._show_custom_points_menu,
            'custom_points_add': self._show_custom_points_add_entry,
            'points_level': self._show_points_level_menu,
            'points_level_add': self._show_points_level_add_entry,
            'points_mall': self._show_points_mall_menu,
            'points_mall_cover': self._show_points_mall_cover_page,
            'points_mall_command': self._show_points_mall_command_page,
            'points_mall_products': self._show_points_mall_products_page,
            'points_mall_orders': self._show_points_mall_orders_page,
            'auction': self._show_auction_menu,
            'bottom_button': self._show_bottom_button_menu,
            'game': self._show_game_menu,
            'guess': self._show_guess_home,
            'engagement': self._show_engagement_home,
            'inherit': self._show_account_inherit_menu,
            'qpub': self._show_quick_publish_menu,
        }

    async def _handle_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackData,
    ) -> None:
        """处理菜单操作"""
        menu_action = callback_data.get(2)
        from backend.features.admin.menu_origins import remember_menu_origin
        remember_menu_origin(context, chat_id=chat_id, feature=menu_action, source=callback_data.get(4))

        handler = self._menu_dispatch().get(menu_action)
        if handler is None:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data=f"adm:menu:main:{chat_id}")],
            ])
            await self.message_helper.safe_edit(
                update,
                text="⚠️ 菜单入口已失效，请返回主菜单重新进入。",
                reply_markup=keyboard,
            )
            return

        await handler(update, context, chat_id)

    async def _show_unimplemented_feature(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackData,
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
        *, callback_data: CallbackData,
    ) -> None:
        """Legacy toggles cannot prove the user's desired final state."""
        await answer_callback_query_safely(update, "此旧开关已更新，请进入功能页选择启用或关闭。")
        field = callback_data.get(2)
        features = {
            "verification_enabled": "verification", "welcome_enabled": "welcome",
            "anti_spam_enabled": "antispam", "anti_flood_enabled": "antispam",
            "sign_enabled": "points", "message_points_enabled": "points",
            "invite_points_enabled": "points", "night_mode_enabled": "night",
            "auto_reply_enabled": "autoreply", "force_subscribe_enabled": "forcesub",
        }
        menu = features.get(field, "settings")
        await self._menu_dispatch()[menu](update, context, chat_id)
