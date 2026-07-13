from __future__ import annotations

from backend.features.activity.services.game_service import (
    parse_ratio as parse_game_ratio,
    resolve_rake_owner as resolve_game_rake_owner,
    update_setting as update_game_setting,
    validate_hhmm as validate_game_hhmm,
)
from backend.features.admin.activity.runtime import admin_handler_instance, clear_private_admin_state
from backend.shared.services.base import ValidationError


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
        if state_type == "game_wait_rake_ratio":
            await update_game_setting(session, target_chat_id, rake_ratio=parse_game_ratio(value))
        elif state_type == "game_wait_rake_owner":
            await update_game_setting(session, target_chat_id, rake_owner_user_id=await resolve_game_rake_owner(session, value))
        elif state_type == "game_wait_auto_start_time":
            await update_game_setting(session, target_chat_id, auto_start_time=validate_game_hhmm(value))
        elif state_type == "game_wait_auto_stop_time":
            await update_game_setting(session, target_chat_id, auto_stop_time=validate_game_hhmm(value))
        else:
            return False
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return True

    await clear_private_admin_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_game_menu(update, context, target_chat_id)
    return True
