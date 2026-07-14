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

HandlerSpec = tuple[tuple[str, ...], ConfigHandler]


def _register_states(handlers: dict[str, ConfigHandler], state_names: Iterable[str], handler: ConfigHandler) -> None:
    for state_name in state_names:
        handlers[state_name] = handler


def _full(states: tuple[str, ...], module: str, name: str) -> HandlerSpec:
    return states, full_args_handler(module, name)


def _update(states: tuple[str, ...], module: str, name: str) -> HandlerSpec:
    return states, update_context_handler(module, name)


def _moderation_specs() -> tuple[HandlerSpec, ...]:
    return (
        _update(("verification_config",), "backend.features.verification.verification_handler", "verification_config_handler"),
        _full(("verification_cover_input", "vfy_agreement_text_input", "vfy_math_prompt_text_input"), "backend.features.admin.module_settings", "handle_verification_input"),
        _full(("anti_flood_config",), "backend.features.moderation.anti_flood_config_handler", "anti_flood_config_message_handler"),
        _full(("anti_spam_config",), "backend.features.moderation.anti_spam_config_handler", "anti_spam_config_message_handler"),
        _full(("garbage_guard_whitelist", "gg_quick_reply_keyword"), "backend.features.moderation.garbage_guard_config_handler", "garbage_guard_whitelist_message_handler"),
        _update(("auto_reply_create", "auto_reply_edit_keywords", "auto_reply_edit_content", "auto_reply_edit_cover", "auto_reply_edit_buttons"), "backend.features.moderation.auto_reply_handler", "auto_reply_config_handler"),
        _update(("banned_word_add",), "backend.features.moderation.banned_word_handler", "banned_word_config_handler"),
    )


def _automation_specs() -> tuple[HandlerSpec, ...]:
    ad_states = (
        "ads_create_config", "ads_rule_edit_start", "ads_rule_edit_interval", "ads_rule_edit_delay",
        "ads_item_edit_title", "ads_item_edit_text", "ads_item_edit_cover", "ads_item_edit_start",
        "ads_item_edit_end", "ads_item_edit_order",
    )
    return (
        _update(("lottery_create",), "backend.features.activity.lottery_handler", "lottery_message_handler"),
        _update(ad_states, "backend.features.automation.ads_handler", "ads_create_config_message"),
        _update(("solitaire_create",), "backend.features.activity.solitaire_handler", "solitaire_create_config_message"),
        (("invite_link_create", "invite_link_cover_input", "invite_link_text_input"), handle_invite_link_config),
        (("quick_publish_input",), handle_quick_publish_input),
        (("sm_edit_title", "sm_edit_text", "sm_edit_buttons", "sm_edit_start_at", "sm_edit_end_at"), scheduled_message_text_input),
        (("sm_edit_media",), scheduled_message_media_input),
    )


def _module_setting_specs() -> tuple[HandlerSpec, ...]:
    force_states = (
        "force_subscribe_channel_1_input", "force_subscribe_channel_2_input",
        "force_subscribe_text_input", "force_subscribe_cover_input", "force_subscribe_buttons_input",
    )
    lock_states = (
        "group_lock_open_keyword_input", "group_lock_close_keyword_input",
        "group_lock_open_time_input", "group_lock_close_time_input",
    )
    module = "backend.features.admin.module_settings"
    return (
        _full(force_states, module, "handle_force_subscribe_channel_input"),
        _full(("new_member_limit_text_input",), module, "handle_new_member_limit_input"),
        _full(("night_mode_text_input",), module, "handle_night_mode_input"),
        _full(("command_config_alias_input",), module, "handle_command_config_input"),
        _full(lock_states, module, "handle_group_lock_text_input"),
        _full(("rename_monitor_text_input",), module, "handle_rename_monitor_text_input"),
    )


def _garage_specs() -> tuple[HandlerSpec, ...]:
    forward_states = ("garage_forward_source_input", "garage_forward_keyword_input", "garage_forward_buttons_input")
    self_states = (
        "teacher_self_location_input", "teacher_self_region_input",
        "teacher_self_price_input", "teacher_self_labels_input",
    )
    return (
        _full(("alliance_create_name_input", "alliance_join_code_input"), "backend.features.admin.garage", "handle_alliance_input"),
        _full(forward_states, "backend.features.admin.garage", "handle_garage_forward_input"),
        _full(("teacher_member_location_input",), "backend.features.admin.garage.teacher_search_inputs", "handle_teacher_member_location_input"),
        _full(self_states, "backend.features.admin.garage.teacher_self", "handle_teacher_self_input"),
        _full(("car_review_submit_teacher_input", "car_review_submit_body_input"), "backend.features.admin.garage.review_submit", "handle_car_review_submit_input"),
    )


def _garage_feature_specs() -> tuple[HandlerSpec, ...]:
    states = (
        "garage_badge_input", "garage_teacher_input", "garage_whitelist_input",
        "garage_limit_interval_input", "garage_limit_max_count_input", "teacher_footer_button_input",
        "teacher_footer_text_input", "teacher_footer_link_input", "teacher_attend_target_input",
        "teacher_att_open_input", "teacher_att_full_input", "teacher_att_rest_input",
        "teacher_delegate_target_input", "teacher_delegate_location_input",
        "car_review_submit_command_input", "car_review_rank_command_input", "car_review_approver_input",
        "car_review_template_input", "car_review_reward_points_input", "car_review_field_add_input",
        "car_review_field_label_input",
    )
    return (_full(states, "backend.features.admin.garage", "handle_garage_features_input"),)


def _points_activity_specs() -> tuple[HandlerSpec, ...]:
    points_states = (
        "custom_points_name_input", "custom_points_rank_input", "custom_points_adjust_input",
        "points_level_name_input", "points_level_threshold_input", "points_mall_command_input",
        "points_mall_cover_input", "points_mall_product_name_input", "points_mall_product_price_input",
        "points_mall_product_limit_input", "points_mall_product_stock_input", "points_mall_fulfiller_input",
        "points_mall_desc_input", "points_mall_product_sort_input", "points_mall_product_cover_input",
    )
    guess_states = (
        "guess_wait_title", "guess_wait_cover", "guess_wait_description", "guess_wait_banker",
        "guess_wait_pool", "guess_wait_options", "guess_wait_command", "guess_wait_deadline",
        "guess_wait_rake_ratio", "guess_wait_rake_owner",
    )
    return (
        _full(points_states, "backend.features.admin.points_extended", "handle_points_extended_input"),
        _full(("bottom_button_text_input", "bottom_button_button_text_input", "bottom_button_payload_input"), "backend.features.admin.activity", "handle_bottom_button_input"),
        _full(("game_wait_rake_ratio", "game_wait_rake_owner", "game_wait_auto_start_time", "game_wait_auto_stop_time"), "backend.features.admin.activity", "handle_game_input"),
        _full(guess_states, "backend.features.admin.activity", "handle_guess_input"),
        _full(("engagement_wait_egg_template", "engagement_wait_chat_target", "engagement_wait_chat_plan", "engagement_wait_chat_command"), "backend.features.admin.activity", "handle_engagement_input"),
    )


def _misc_specs() -> tuple[HandlerSpec, ...]:
    return (
        _full(("renewal_card_input", "renewal_enter_code"), "backend.features.subscription.renewal_handler", "handle_renewal_card_input"),
        _full(("welcome_title_input", "welcome_text_input", "welcome_cover_input"), "backend.features.admin.welcome", "handle_welcome_input"),
        _full(("button_editor_text_input", "button_editor_url_input", "button_editor_payload_input"), "backend.shared.button_layout_editor", "handle_button_layout_editor_input"),
        _full(("inherit_wait_token_input",), "backend.features.invite.account_inherit_handler", "handle_account_inherit_input"),
        (("nearby_edit_price", "nearby_edit_method", "nearby_edit_address"), nearby_text_input),
        (("nearby_edit_location",), nearby_location_input),
    )


def build_private_config_handlers() -> dict[str, ConfigHandler]:
    handlers: dict[str, ConfigHandler] = {}
    spec_groups = (
        _moderation_specs(), _automation_specs(), _module_setting_specs(), _garage_specs(),
        _garage_feature_specs(), _points_activity_specs(), _misc_specs(),
    )
    for specs in spec_groups:
        for states, handler in specs:
            _register_states(handlers, states, handler)
    return handlers
