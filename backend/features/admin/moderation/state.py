from __future__ import annotations

from backend.features.admin.support import *


class ModerationStateMixin:
    async def _start_text_input_state(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        state_chat_id: int,
        *, state_type: str,
        payload: dict,
    ) -> None:
        from backend.platform.state.conversation_state_service import SELECTED_CHAT_STATE
        from backend.platform.state.state_service import clear_private_input_state, clear_user_state, set_user_state

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await clear_user_state(session, chat_id=state_chat_id, user_id=user_id)
            if state_chat_id != user_id:
                await clear_private_input_state(session, user_id)
                await set_user_state(
                    session,
                    chat_id=user_id,
                    user_id=user_id,
                    state_type=SELECTED_CHAT_STATE,
                    state_data={"managed_chat_id": state_chat_id},
                )
            await set_user_state(
                session,
                chat_id=state_chat_id,
                user_id=user_id,
                state_type=state_type,
                state_data=payload,
            )
            await session.commit()
