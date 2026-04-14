from __future__ import annotations

from backend.features.admin.activity.controller import ActivityAdminControllerMixin
from backend.features.admin.core.controller import CoreAdminControllerMixin
from backend.features.admin.garage.controller import GarageAdminControllerMixin
from backend.features.admin.import_export.controller import ImportExportAdminControllerMixin
from backend.features.admin.moderation.controller import ModerationAdminControllerMixin
from backend.features.admin.points.controller import PointsAdminControllerMixin
from backend.features.admin.subscription.controller import SubscriptionAdminControllerMixin
from backend.features.admin.welcome.controller import WelcomeAdminControllerMixin
from backend.platform.telegram.errors import mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.base_handler import BaseHandler
from telegram import Update
from telegram.ext import ContextTypes


PREFIX_HANDLERS = {
    "ali": "_handle_alliance",
    "gfw": "_handle_garage_forward",
    "grg": "_handle_garage_auth",
    "tsearch": "_handle_teacher_search",
    "crv": "_handle_car_review",
    "auc": "_handle_auction",
    "btm": "_handle_bottom_button",
    "gm": "_handle_game",
    "guess": "_handle_guess",
    "act": "_handle_engagement",
    "qpub": "_handle_quick_publish",
}

ADM_ACTION_HANDLERS = {
    "menu": "_handle_menu",
    "switch_group": "_handle_switch_group",
    "select_group": "_handle_select_group",
    "back_to_main": "_handle_back_to_main",
    "back_to_menu": "_handle_back_to_menu",
    "toggle": "_handle_toggle",
    "vfy_config": "_handle_verification_config_start",
    "vfy_home": "_handle_verification_home",
    "renewal": "_handle_renewal",
    "perm": "_handle_permission_policy",
    "gl": "_handle_group_lock",
    "rm": "_handle_rename_monitor",
    "fs": "_handle_force_subscribe",
    "nml": "_handle_new_member_limit",
    "night": "_handle_night_mode",
    "gcmd": "_handle_command_config",
    "import": "_handle_import_settings",
    "clone": "_handle_clone_settings",
    "wel": "_handle_welcome",
    "cpt": "_handle_custom_points",
    "lvl": "_handle_points_level",
    "mall": "_handle_points_mall",
    "todo": "_show_unimplemented_feature",
}


class AdminRuntime(
    ActivityAdminControllerMixin,
    GarageAdminControllerMixin,
    PointsAdminControllerMixin,
    ModerationAdminControllerMixin,
    ImportExportAdminControllerMixin,
    SubscriptionAdminControllerMixin,
    WelcomeAdminControllerMixin,
    CoreAdminControllerMixin,
    BaseHandler,
):
    """Admin runtime composed from domain controllers."""

    def __init__(self) -> None:
        super().__init__()
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        q = update.callback_query
        await q.answer()
        mark_callback_query_answered(update)

        callback_data = CallbackParser.parse(q.data)
        prefix = callback_data.get(0)

        prefix_handler = PREFIX_HANDLERS.get(prefix)
        if prefix_handler is not None:
            await getattr(self, prefix_handler)(update, context, target_chat_id, callback_data)
            return

        action = callback_data.get(1)
        if action == "af_config":
            from backend.features.moderation.anti_flood_config_handler import start_anti_flood_config
            await start_anti_flood_config(update, context, target_chat_id)
            return

        if action == "as_config":
            from backend.features.moderation.anti_spam_config_handler import start_anti_spam_config
            await start_anti_spam_config(update, context, target_chat_id)
            return

        action_handler = ADM_ACTION_HANDLERS.get(action)
        if action_handler is None:
            return
        await getattr(self, action_handler)(update, context, target_chat_id, callback_data)


admin_runtime = AdminRuntime()
