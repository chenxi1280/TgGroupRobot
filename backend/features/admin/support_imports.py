from __future__ import annotations

import asyncio
import io
import json
import re
import structlog

from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from backend.features.activity.services.auction_service import (
    format_auction_settings_text,
    get_auction,
    get_or_create_setting as get_auction_setting,
    list_auctions,
    list_recent_auctions,
    update_setting as update_auction_setting,
)
from backend.features.activity.services.engagement_service import (
    archive_egg_snapshot,
    create_egg_event,
    get_chat_reward_top_users,
    get_clue_reward_points,
    get_egg_event,
    get_egg_event_counts,
    get_latest_running_egg_event,
    get_or_create_chat_reward as get_engagement_chat_reward,
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
from backend.features.activity.services.game_service import (
    format_game_menu_text,
    get_or_create_setting as get_game_setting,
    get_game_points_chat_label,
    get_rake_owner_label as get_game_rake_owner_label,
    get_round_participants as get_game_round_participants,
    list_recent_rounds as list_recent_game_rounds,
    parse_ratio as parse_game_ratio,
    resolve_rake_owner as resolve_game_rake_owner,
    update_setting as update_game_setting,
    validate_hhmm as validate_game_hhmm,
)
from backend.features.activity.services.guess_service import (
    cancel_event as cancel_guess_event,
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
    update_setting as update_guess_setting,
)
from backend.features.admin.activity import (
    handle_bottom_button_input,
    handle_engagement_input,
    handle_game_input,
    handle_guess_input,
)
from backend.features.admin.garage import (
    handle_alliance_input,
    handle_garage_features_input,
    handle_garage_forward_input,
)
from backend.features.admin.module_settings import (
    build_force_subscribe_preview_markup as _build_force_subscribe_preview_markup,
    format_duration_label as _format_duration_label,
    handle_command_config_input,
    handle_force_subscribe_channel_input,
    handle_group_lock_text_input,
    handle_new_member_limit_input,
    handle_night_mode_input,
    handle_rename_monitor_text_input,
    handle_verification_input,
    is_valid_hhmm as _is_valid_hhmm,
)
from backend.features.admin.points_extended import handle_points_extended_input
from backend.features.admin.ui.admin_main import (
    admin_main_menu,
    create_group_selection_keyboard,
    create_guide_keyboard,
    format_admin_main_menu_text,
    format_verification_menu_text,
    toggle_menu,
    verification_mode_menu,
)
from backend.features.admin.ui.points_extended import (
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
from backend.features.admin.welcome import handle_welcome_input
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.group_ops.services.bottom_button_service import (
    add_layout_button,
    build_management_layout_preview,
    clear_layouts as clear_bottom_button_layouts,
    compact_layouts as compact_bottom_button_layouts,
    delete_layout_button,
    generate_buttons as generate_bottom_buttons,
    get_layout as get_bottom_button_layout,
    get_or_create_setting as get_bottom_button_setting,
    list_layouts as list_bottom_button_layouts,
    update_layout_button,
    update_setting as update_bottom_button_setting,
)
from backend.features.group_ops.services.chat_group_service import get_user_managed_chats, set_user_current_chat
from backend.features.invite.services.account_inherit_service import build_summary as build_inherit_summary
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.platform.config.core.settings import get_settings
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_private_input_state, clear_user_state, get_user_state, set_user_state
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.i18n.strings import t
from backend.shared.services.base import ValidationError
from backend.shared.services.chat_service import ensure_chat, get_chat_settings, get_settings_toggle_rows
from backend.shared.services.command_config_service import (
    ensure_command_enabled,
    get_command_config,
    list_command_definitions,
    set_command_alias,
    set_command_enabled,
)
from backend.shared.services.import_settings_service import apply_import, list_import_modules
from backend.shared.services.permission_service import PermissionPolicyService, is_user_admin
from backend.shared.services.user_service import ensure_user

log = structlog.get_logger(__name__)

__all__ = [name for name in globals() if not name.startswith("__")]
