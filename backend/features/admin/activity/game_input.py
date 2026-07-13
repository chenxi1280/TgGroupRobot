from __future__ import annotations

from backend.features.activity.services.game_service import (
    parse_ratio as parse_game_ratio,
    resolve_rake_owner as resolve_game_rake_owner,
    update_setting as update_game_setting,
    validate_hhmm as validate_game_hhmm,
)
from backend.features.admin.activity.runtime import admin_handler_instance, clear_private_admin_state
from backend.shared.services.base import ValidationError


async def _apply_game_admin_value(
    session,
    target_chat_id: int,
    *,
    state_type: str,
    value: str,
) -> bool:
    if state_type == "game_wait_rake_ratio":
        await update_game_setting(session, target_chat_id, rake_ratio=parse_game_ratio(value))
        return True
    if state_type == "game_wait_rake_owner":
        owner_id = await resolve_game_rake_owner(session, value)
        await update_game_setting(session, target_chat_id, rake_owner_user_id=owner_id)
        return True
    if state_type == "game_wait_auto_start_time":
        await update_game_setting(session, target_chat_id, auto_start_time=validate_game_hhmm(value))
        return True
    if state_type == "game_wait_auto_stop_time":
        await update_game_setting(session, target_chat_id, auto_stop_time=validate_game_hhmm(value))
        return True
    return False


async def handle_game_admin_input(
    update,
    context,
    session,
    *, state,
    message_text: str,

    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    value = message_text.strip()
    state_type = str(state.state_type)
    try:
        if not await _apply_game_admin_value(
            session,
            target_chat_id,
            state_type=state_type,
            value=value,
        ):
            return False
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return True

    await clear_private_admin_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_game_menu(update, context, target_chat_id)
    return True
