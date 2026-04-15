from __future__ import annotations


def admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


async def clear_private_admin_state(session, *, target_chat_id: int, user_id: int) -> None:
    from backend.platform.state.state_service import clear_private_input_state, clear_user_state

    await clear_user_state(session, chat_id=target_chat_id, user_id=user_id)
    if target_chat_id != user_id:
        await clear_private_input_state(session, user_id)
