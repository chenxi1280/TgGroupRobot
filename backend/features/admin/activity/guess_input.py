from __future__ import annotations

import re

from backend.features.activity.services.guess_service import (
    parse_deadline as parse_guess_deadline,
    parse_options as parse_guess_options,
    parse_ratio as parse_guess_ratio,
    resolve_user_id as resolve_guess_user_id,
    update_setting as update_guess_setting,
)
from backend.features.admin.activity.runtime import admin_handler_instance
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.shared.services.base import ValidationError


async def handle_guess_admin_input(
    update,
    context,
    session,
    state,
    message_text: str,
    *,
    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    state_type = str(state.state_type)
    if not state_type.startswith("guess_"):
        return False

    user_id = update.effective_user.id
    draft = dict(state.state_data or {})
    value = message_text.strip()

    async def _save_draft(next_type: str = "guess_wait_title") -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=user_id)
        await set_user_state(
            session,
            chat_id=user_id,
            user_id=user_id,
            state_type=next_type,
            state_data=draft,
        )

    if state_type == "guess_wait_rake_ratio":
        try:
            await update_guess_setting(session, target_chat_id, rake_ratio=parse_guess_ratio(value))
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
        await clear_user_state(session, chat_id=user_id, user_id=user_id)
        await session.commit()
        await admin_handler_instance()._show_guess_settings(update, context, target_chat_id)
        return True

    if state_type == "guess_wait_rake_owner":
        try:
            await update_guess_setting(session, target_chat_id, rake_owner_user_id=await resolve_guess_user_id(session, value))
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
        await clear_user_state(session, chat_id=user_id, user_id=user_id)
        await session.commit()
        await admin_handler_instance()._show_guess_settings(update, context, target_chat_id)
        return True

    try:
        if state_type == "guess_wait_title":
            if not value:
                await update.effective_message.reply_text("活动名字不能为空。")
                return True
            draft["title"] = value[:128]
        elif state_type == "guess_wait_cover":
            if value == "清空":
                draft["cover_file_id"] = None
            elif update.effective_message.photo:
                draft["cover_file_id"] = update.effective_message.photo[-1].file_id
            else:
                await update.effective_message.reply_text("请发送图片，或发送“清空”。")
                return True
        elif state_type == "guess_wait_description":
            draft["description"] = value
        elif state_type == "guess_wait_banker":
            banker_user_id = await resolve_guess_user_id(session, value)
            draft["banker_user_id"] = banker_user_id
            draft["mode"] = "banker" if banker_user_id else "no_banker"
        elif state_type == "guess_wait_pool":
            if not re.fullmatch(r"\d+", value):
                await update.effective_message.reply_text("公共奖池必须是非负整数。")
                return True
            draft["public_pool"] = int(value)
        elif state_type == "guess_wait_options":
            draft["options"] = parse_guess_options(value)
        elif state_type == "guess_wait_command":
            if not value:
                await update.effective_message.reply_text("群内指令不能为空。")
                return True
            draft["command_keyword"] = value[:32]
        elif state_type == "guess_wait_deadline":
            draft["deadline_at"] = parse_guess_deadline(value).isoformat()
        else:
            await update.effective_message.reply_text("当前竞猜配置状态不支持该输入，请重新进入配置页面。")
            return True
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return True

    await _save_draft()
    await session.commit()
    await admin_handler_instance()._show_guess_create_menu(update, context, target_chat_id, draft)
    return True
