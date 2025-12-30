from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ConversationState


async def get_user_state(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> ConversationState | None:
    """获取用户的当前对话状态"""
    stmt = select(ConversationState).where(
        ConversationState.chat_id == chat_id,
        ConversationState.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def set_user_state(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    state_type: str,
    state_data: dict | None = None,
) -> ConversationState:
    """设置用户的对话状态"""
    state = await get_user_state(session, chat_id, user_id)
    if state is None:
        state = ConversationState(
            chat_id=chat_id,
            user_id=user_id,
            state_type=state_type,
            state_data=state_data or {},
        )
        session.add(state)
    else:
        state.state_type = state_type
        state.state_data = state_data or {}
    return state


async def clear_user_state(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> None:
    """清除用户的对话状态"""
    state = await get_user_state(session, chat_id, user_id)
    if state is not None:
        await session.delete(state)

