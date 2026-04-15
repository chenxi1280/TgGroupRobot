from __future__ import annotations


def admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


def admin_module():
    import backend.features.admin.admin_handler as admin_handler_module

    return admin_handler_module


async def clear_points_state(session, *, target_chat_id: int, user_id: int) -> None:
    module = admin_module()
    await module.clear_user_state(session, chat_id=target_chat_id, user_id=user_id)
    if target_chat_id != user_id:
        await module.clear_private_input_state(session, user_id)


def parse_state_int(state, key: str) -> int | None:
    raw = state.state_data.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
