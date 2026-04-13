from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.services.engagement_service import (
    parse_reward_plan as parse_engagement_reward_plan,
    update_chat_reward as update_engagement_chat_reward,
    update_egg_event_from_template,
)
from backend.features.activity.services.game_service import (
    parse_ratio as parse_game_ratio,
    resolve_rake_owner as resolve_game_rake_owner,
    update_setting as update_game_setting,
    validate_hhmm as validate_game_hhmm,
)
from backend.features.activity.services.guess_service import (
    parse_deadline as parse_guess_deadline,
    parse_options as parse_guess_options,
    parse_ratio as parse_guess_ratio,
    resolve_user_id as resolve_guess_user_id,
    update_setting as update_guess_setting,
)
from backend.features.group_ops.services.bottom_button_service import (
    update_layout_button,
    update_setting as update_bottom_button_setting,
)
from backend.shared.services.base import ValidationError


def _admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


async def handle_bottom_button_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

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
        await _admin_handler_instance()._show_bottom_button_menu(update, context, target_chat_id)
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
        await _admin_handler_instance()._show_bottom_button_detail(update, context, target_chat_id, layout_id)
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
        await _admin_handler_instance()._show_bottom_button_detail(update, context, target_chat_id, layout_id)
        return

    await update.effective_message.reply_text("当前底部按钮配置状态不支持该输入，请重新进入配置页面。")


async def handle_game_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

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
    await _admin_handler_instance()._show_game_menu(update, context, target_chat_id)


async def handle_guess_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state, set_user_state

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
        await _admin_handler_instance()._show_guess_settings(update, context, target_chat_id)
        return

    if state_type == "guess_wait_rake_owner":
        try:
            await update_guess_setting(session, target_chat_id, rake_owner_user_id=await resolve_guess_user_id(session, value))
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await session.commit()
        await _admin_handler_instance()._show_guess_settings(update, context, target_chat_id)
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
    await _admin_handler_instance()._show_guess_create_menu(update, context, target_chat_id, draft)


async def handle_engagement_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

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
            await _admin_handler_instance()._show_engagement_egg(update, context, target_chat_id, event.id)
            return
        if state_type == "engagement_wait_chat_target":
            if not re.fullmatch(r"\d+", value):
                await update.effective_message.reply_text("发言达标数量必须是正整数。")
                return
            await update_engagement_chat_reward(session, target_chat_id, daily_message_target=max(int(value), 1))
            await _clear_state()
            await session.commit()
            await _admin_handler_instance()._show_engagement_chat_reward(update, context, target_chat_id)
            return
        if state_type == "engagement_wait_chat_plan":
            await update_engagement_chat_reward(session, target_chat_id, reward_points_plan=parse_engagement_reward_plan(value))
            await _clear_state()
            await session.commit()
            await _admin_handler_instance()._show_engagement_chat_reward(update, context, target_chat_id)
            return
        if state_type == "engagement_wait_chat_command":
            if not value:
                await update.effective_message.reply_text("领奖口令不能为空。")
                return
            await update_engagement_chat_reward(session, target_chat_id, command_keyword=value[:32])
            await _clear_state()
            await session.commit()
            await _admin_handler_instance()._show_engagement_chat_reward(update, context, target_chat_id)
            return
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await update.effective_message.reply_text("当前促活工具配置状态不支持该输入，请重新进入配置页面。")
