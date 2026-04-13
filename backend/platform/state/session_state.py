from __future__ import annotations

from typing import Any

from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import get_user_state
from backend.shared.handlers.base.chat_resolver import ChatResolver


async def get_scoped_state(
    session: Any,
    db: Database,
    *,
    user_id: int,
    private_chat_id: int,
) -> Any:
    private_state = await get_user_state(session, chat_id=private_chat_id, user_id=user_id)
    if private_state is not None:
        return private_state

    target_chat_id = await ChatResolver.get_current_chat(db, user_id)
    if target_chat_id:
        return await get_user_state(session, chat_id=target_chat_id, user_id=user_id)

    return None

