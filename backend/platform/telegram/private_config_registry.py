"""Private config state registry."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from functools import lru_cache
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

ConfigHandler = Callable[
    [Update, ContextTypes.DEFAULT_TYPE, AsyncSession, Any, str],
    Awaitable[None],
]


@lru_cache(maxsize=None)
def _resolve_attr(module_path: str, attr_name: str):
    return getattr(import_module(module_path), attr_name)


def _update_context_handler(module_path: str, func_name: str) -> ConfigHandler:
    async def handler(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        del session, state, message_text
        func = _resolve_attr(module_path, func_name)
        await func(update, context)

    return handler


def _full_args_handler(module_path: str, func_name: str) -> ConfigHandler:
    async def handler(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        func = _resolve_attr(module_path, func_name)
        await func(update, context, session, state, message_text)

    return handler


async def _handle_invite_link_config(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    invite_link_create_name_message = _resolve_attr(
        "backend.features.invite.invite_link_handler",
        "invite_link_create_name_message",
    )
    handle_invite_link_config_input = _resolve_attr(
        "backend.features.invite.invite_link_handler",
        "handle_invite_link_config_input",
    )

    if state.state_type == "invite_link_create":
        await invite_link_create_name_message(update, context)
        return

    await handle_invite_link_config_input(update, context, session, state, message_text)


async def handle_quick_publish_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    parse_buttons_text = _resolve_attr(
        "backend.features.automation.scheduled_message_handler",
        "_parse_buttons_text",
    )
    ValidationError = _resolve_attr("backend.shared.services.base", "ValidationError")
    admin_handler = import_module("backend.features.admin.admin_handler")

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    field = state.state_data.get("field")

    drafts = context.user_data.setdefault("quick_publish_draft", {})
    draft = drafts.setdefault(
        str(target_chat_id),
        {"text": "", "media_type": None, "media_file_id": None, "buttons": []},
    )

    text_value = (message_text or "").strip()

    if field == "text":
        if not text_value:
            await update.effective_message.reply_text("文本不能为空。")
            return
        draft["text"] = text_value
    elif field == "media":
        if text_value.lower().startswith("/clear"):
            draft["media_type"] = None
            draft["media_file_id"] = None
            if text_value.strip() == "/clear":
                draft["text"] = draft.get("text", "")
        else:
            msg = update.effective_message
            if msg.photo:
                draft["media_type"] = "photo"
                draft["media_file_id"] = msg.photo[-1].file_id
            elif msg.video:
                draft["media_type"] = "video"
                draft["media_file_id"] = msg.video.file_id
            elif msg.document:
                draft["media_type"] = "document"
                draft["media_file_id"] = msg.document.file_id
            elif msg.animation:
                draft["media_type"] = "animation"
                draft["media_file_id"] = msg.animation.file_id
            else:
                await update.effective_message.reply_text("请发送图片/视频/文件作为媒体内容。")
                return
            if text_value:
                draft["text"] = text_value
    elif field == "buttons":
        if text_value.lower().startswith("/clear"):
            draft["buttons"] = []
        else:
            try:
                buttons = parse_buttons_text(text_value)
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
            draft["buttons"] = buttons
    else:
        await update.effective_message.reply_text("快捷发布状态异常，请重新进入。")
        return

    state_service = import_module("backend.platform.state.state_service")
    await state_service.clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
    await state_service.clear_user_state(
        session,
        chat_id=update.effective_user.id,
        user_id=update.effective_user.id,
    )
    await session.commit()
    await admin_handler._admin_handler._show_quick_publish_menu(update, context, target_chat_id)


async def _scheduled_message_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    del session
    if update.effective_user is None:
        return

    scheduled_message_handler = _resolve_attr(
        "backend.features.automation.scheduled_message_handler",
        "_scheduled_message_handler",
    )
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    await scheduled_message_handler.handle_fsm_input(
        update,
        context,
        target_chat_id,
        update.effective_user.id,
        message_text,
    )


async def _scheduled_message_media_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    del session, message_text
    if update.effective_user is None:
        return

    scheduled_message_handler = _resolve_attr(
        "backend.features.automation.scheduled_message_handler",
        "_scheduled_message_handler",
    )
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    await scheduled_message_handler.handle_media_input(
        update,
        context,
        target_chat_id,
        update.effective_user.id,
    )


async def _nearby_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    nearby_handler = _resolve_attr("backend.features.nearby.nearby_handler", "_nearby_handler")
    await nearby_handler.handle_fsm_text_input(update, context, session, state, message_text)


async def _nearby_location_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    del message_text
    nearby_handler = _resolve_attr("backend.features.nearby.nearby_handler", "_nearby_handler")
    await nearby_handler.handle_fsm_location_input(update, context, session, state)


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
        _update_context_handler("backend.features.verification.verification_handler", "verification_config_handler"),
    )
    _register_states(
        handlers,
        ["anti_flood_config"],
        _full_args_handler("backend.features.moderation.anti_flood_config_handler", "anti_flood_config_message_handler"),
    )
    _register_states(
        handlers,
        ["anti_spam_config"],
        _full_args_handler("backend.features.moderation.anti_spam_config_handler", "anti_spam_config_message_handler"),
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
        _update_context_handler("backend.features.moderation.auto_reply_handler", "auto_reply_config_handler"),
    )
    _register_states(
        handlers,
        ["banned_word_add"],
        _update_context_handler("backend.features.moderation.banned_word_handler", "banned_word_config_handler"),
    )
    _register_states(
        handlers,
        ["lottery_create"],
        _update_context_handler("backend.features.activity.lottery_handler", "lottery_message_handler"),
    )
    _register_states(
        handlers,
        ["ads_create_config"],
        _update_context_handler("backend.features.automation.ads_handler", "ads_create_config_message"),
    )
    _register_states(
        handlers,
        ["solitaire_create"],
        _update_context_handler("backend.features.activity.solitaire_handler", "solitaire_create_config_message"),
    )
    _register_states(
        handlers,
        [
            "invite_link_create",
            "invite_link_cover_input",
            "invite_link_text_input",
            "invite_link_buttons_input",
        ],
        _handle_invite_link_config,
    )
    _register_states(
        handlers,
        ["renewal_card_input", "renewal_enter_code"],
        _full_args_handler("backend.features.subscription.renewal_handler", "handle_renewal_card_input"),
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
        _full_args_handler("backend.features.admin.module_settings", "handle_force_subscribe_channel_input"),
    )
    _register_states(
        handlers,
        ["new_member_limit_text_input"],
        _full_args_handler("backend.features.admin.module_settings", "handle_new_member_limit_input"),
    )
    _register_states(
        handlers,
        ["night_mode_text_input"],
        _full_args_handler("backend.features.admin.module_settings", "handle_night_mode_input"),
    )
    _register_states(
        handlers,
        ["command_config_alias_input"],
        _full_args_handler("backend.features.admin.module_settings", "handle_command_config_input"),
    )
    _register_states(
        handlers,
        [
            "group_lock_open_keyword_input",
            "group_lock_close_keyword_input",
            "group_lock_open_time_input",
            "group_lock_close_time_input",
        ],
        _full_args_handler("backend.features.admin.module_settings", "handle_group_lock_text_input"),
    )
    _register_states(
        handlers,
        ["rename_monitor_text_input"],
        _full_args_handler("backend.features.admin.module_settings", "handle_rename_monitor_text_input"),
    )
    _register_states(
        handlers,
        [
            "welcome_title_input",
            "welcome_text_input",
            "welcome_cover_input",
            "welcome_buttons_input",
        ],
        _full_args_handler("backend.features.admin.welcome", "handle_welcome_input"),
    )
    _register_states(
        handlers,
        ["alliance_create_name_input", "alliance_join_code_input"],
        _full_args_handler("backend.features.admin.garage", "handle_alliance_input"),
    )
    _register_states(
        handlers,
        [
            "garage_forward_source_input",
            "garage_forward_keyword_input",
            "garage_forward_buttons_input",
        ],
        _full_args_handler("backend.features.admin.garage", "handle_garage_forward_input"),
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
        _full_args_handler("backend.features.admin.garage", "handle_garage_features_input"),
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
        _full_args_handler("backend.features.admin.points_extended", "handle_points_extended_input"),
    )
    _register_states(
        handlers,
        ["bottom_button_text_input", "bottom_button_button_text_input", "bottom_button_payload_input"],
        _full_args_handler("backend.features.admin.activity", "handle_bottom_button_input"),
    )
    _register_states(
        handlers,
        [
            "game_wait_rake_ratio",
            "game_wait_rake_owner",
            "game_wait_auto_start_time",
            "game_wait_auto_stop_time",
        ],
        _full_args_handler("backend.features.admin.activity", "handle_game_input"),
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
        _full_args_handler("backend.features.admin.activity", "handle_guess_input"),
    )
    _register_states(
        handlers,
        [
            "engagement_wait_egg_template",
            "engagement_wait_chat_target",
            "engagement_wait_chat_plan",
            "engagement_wait_chat_command",
        ],
        _full_args_handler("backend.features.admin.activity", "handle_engagement_input"),
    )
    _register_states(
        handlers,
        ["inherit_wait_token_input"],
        _full_args_handler("backend.features.invite.account_inherit_handler", "handle_account_inherit_input"),
    )
    _register_states(handlers, ["quick_publish_input"], handle_quick_publish_input)
    _register_states(
        handlers,
        ["sm_edit_text", "sm_edit_buttons", "sm_edit_start_at", "sm_edit_end_at"],
        _scheduled_message_text_input,
    )
    _register_states(handlers, ["sm_edit_media"], _scheduled_message_media_input)
    _register_states(
        handlers,
        ["nearby_edit_price", "nearby_edit_method", "nearby_edit_address"],
        _nearby_text_input,
    )
    _register_states(handlers, ["nearby_edit_location"], _nearby_location_input)

    return handlers

