"""Private config state registry."""
from __future__ import annotations

from collections.abc import Iterable

from backend.platform.telegram.private_config_adapters import (
    ConfigHandler,
    full_args_handler,
    handle_invite_link_config,
    handle_quick_publish_input,
    nearby_location_input,
    nearby_text_input,
    scheduled_message_media_input,
    scheduled_message_text_input,
    update_context_handler,
)


def _register_states(
    handlers: dict[str, ConfigHandler],
    state_names: Iterable[str],
    handler: ConfigHandler,
) -> None:
    for state_name in state_names:
        handlers[state_name] = handler


def build_private_config_handlers() -> dict[str, ConfigHandler]:
    handlers: dict[str, ConfigHandler] = {}

    _register_states(
        handlers,
        ["verification_config"],
        update_context_handler("backend.features.verification.verification_handler", "verification_config_handler"),
    )
    _register_states(
        handlers,
        ["anti_flood_config"],
        full_args_handler("backend.features.moderation.anti_flood_config_handler", "anti_flood_config_message_handler"),
    )
    _register_states(
        handlers,
        ["anti_spam_config"],
        full_args_handler("backend.features.moderation.anti_spam_config_handler", "anti_spam_config_message_handler"),
    )
    _register_states(
        handlers,
        [
            "auto_reply_create",
            "auto_reply_edit_keywords",
            "auto_reply_edit_content",
            "auto_reply_edit_cover",
            "auto_reply_edit_buttons",
        ],
        update_context_handler("backend.features.moderation.auto_reply_handler", "auto_reply_config_handler"),
    )
    _register_states(
        handlers,
        ["banned_word_add"],
        update_context_handler("backend.features.moderation.banned_word_handler", "banned_word_config_handler"),
    )
    _register_states(
        handlers,
        ["lottery_create"],
        update_context_handler("backend.features.activity.lottery_handler", "lottery_message_handler"),
    )
    _register_states(
        handlers,
        ["ads_create_config"],
        update_context_handler("backend.features.automation.ads_handler", "ads_create_config_message"),
    )
    _register_states(
        handlers,
        ["solitaire_create"],
        update_context_handler("backend.features.activity.solitaire_handler", "solitaire_create_config_message"),
    )
    _register_states(
        handlers,
        [
            "invite_link_create",
            "invite_link_cover_input",
            "invite_link_text_input",
            "invite_link_buttons_input",
        ],
        handle_invite_link_config,
    )
    _register_states(
        handlers,
        ["renewal_card_input", "renewal_enter_code"],
        full_args_handler("backend.features.subscription.renewal_handler", "handle_renewal_card_input"),
    )
    _register_states(
        handlers,
        [
            "force_subscribe_channel_1_input",
            "force_subscribe_channel_2_input",
            "force_subscribe_text_input",
            "force_subscribe_cover_input",
            "force_subscribe_buttons_input",
        ],
        full_args_handler("backend.features.admin.module_settings", "handle_force_subscribe_channel_input"),
    )
    _register_states(
        handlers,
        ["new_member_limit_text_input"],
        full_args_handler("backend.features.admin.module_settings", "handle_new_member_limit_input"),
    )
    _register_states(
        handlers,
        ["night_mode_text_input"],
        full_args_handler("backend.features.admin.module_settings", "handle_night_mode_input"),
    )
    _register_states(
        handlers,
        ["command_config_alias_input"],
        full_args_handler("backend.features.admin.module_settings", "handle_command_config_input"),
    )
    _register_states(
        handlers,
        [
            "group_lock_open_keyword_input",
            "group_lock_close_keyword_input",
            "group_lock_open_time_input",
            "group_lock_close_time_input",
        ],
        full_args_handler("backend.features.admin.module_settings", "handle_group_lock_text_input"),
    )
    _register_states(
        handlers,
        ["rename_monitor_text_input"],
        full_args_handler("backend.features.admin.module_settings", "handle_rename_monitor_text_input"),
    )
    _register_states(
        handlers,
        [
            "welcome_title_input",
            "welcome_text_input",
            "welcome_cover_input",
            "welcome_buttons_input",
        ],
        full_args_handler("backend.features.admin.welcome", "handle_welcome_input"),
    )
    _register_states(
        handlers,
        ["alliance_create_name_input", "alliance_join_code_input"],
        full_args_handler("backend.features.admin.garage", "handle_alliance_input"),
    )
    _register_states(
        handlers,
        [
            "garage_forward_source_input",
            "garage_forward_keyword_input",
            "garage_forward_buttons_input",
        ],
        full_args_handler("backend.features.admin.garage", "handle_garage_forward_input"),
    )
    _register_states(
        handlers,
        [
            "garage_badge_input",
            "garage_teacher_input",
            "garage_whitelist_input",
            "garage_limit_interval_input",
            "garage_limit_max_count_input",
            "teacher_search_delegate_target_input",
            "teacher_search_delegate_location_input",
            "car_review_submit_command_input",
            "car_review_rank_command_input",
            "car_review_approver_input",
            "car_review_template_input",
            "car_review_reward_points_input",
        ],
        full_args_handler("backend.features.admin.garage", "handle_garage_features_input"),
    )
    _register_states(
        handlers,
        [
            "custom_points_name_input",
            "custom_points_rank_input",
            "custom_points_adjust_input",
            "points_level_name_input",
            "points_level_threshold_input",
            "points_mall_command_input",
            "points_mall_cover_input",
            "points_mall_product_name_input",
            "points_mall_product_price_input",
            "points_mall_product_limit_input",
            "points_mall_product_stock_input",
            "points_mall_product_fulfiller_input",
            "points_mall_product_description_input",
            "points_mall_product_sort_input",
            "points_mall_product_cover_input",
        ],
        full_args_handler("backend.features.admin.points_extended", "handle_points_extended_input"),
    )
    _register_states(
        handlers,
        ["bottom_button_text_input", "bottom_button_button_text_input", "bottom_button_payload_input"],
        full_args_handler("backend.features.admin.activity", "handle_bottom_button_input"),
    )
    _register_states(
        handlers,
        [
            "game_wait_rake_ratio",
            "game_wait_rake_owner",
            "game_wait_auto_start_time",
            "game_wait_auto_stop_time",
        ],
        full_args_handler("backend.features.admin.activity", "handle_game_input"),
    )
    _register_states(
        handlers,
        [
            "guess_wait_title",
            "guess_wait_cover",
            "guess_wait_description",
            "guess_wait_banker",
            "guess_wait_pool",
            "guess_wait_options",
            "guess_wait_command",
            "guess_wait_deadline",
            "guess_wait_rake_ratio",
            "guess_wait_rake_owner",
        ],
        full_args_handler("backend.features.admin.activity", "handle_guess_input"),
    )
    _register_states(
        handlers,
        [
            "engagement_wait_egg_template",
            "engagement_wait_chat_target",
            "engagement_wait_chat_plan",
            "engagement_wait_chat_command",
        ],
        full_args_handler("backend.features.admin.activity", "handle_engagement_input"),
    )
    _register_states(
        handlers,
        ["inherit_wait_token_input"],
        full_args_handler("backend.features.invite.account_inherit_handler", "handle_account_inherit_input"),
    )
    _register_states(handlers, ["quick_publish_input"], handle_quick_publish_input)
    _register_states(
        handlers,
        ["sm_edit_text", "sm_edit_buttons", "sm_edit_start_at", "sm_edit_end_at"],
        scheduled_message_text_input,
    )
    _register_states(handlers, ["sm_edit_media"], scheduled_message_media_input)
    _register_states(
        handlers,
        ["nearby_edit_price", "nearby_edit_method", "nearby_edit_address"],
        nearby_text_input,
    )
    _register_states(handlers, ["nearby_edit_location"], nearby_location_input)

    return handlers
