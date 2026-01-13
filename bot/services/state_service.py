from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ConversationState

log = structlog.get_logger(__name__)


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
    state = result.scalar_one_or_none()
    log.info(
        "get_user_state_result",
        chat_id=chat_id,
        user_id=user_id,
        state_found=state is not None,
        state_type=state.state_type if state else None,
    )
    return state


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
        # 立即 flush 确保 INSERT 语句被执行
        await session.flush()
        log.info(
            "state_created_and_flushed",
            chat_id=chat_id,
            user_id=user_id,
            state_type=state_type,
        )
    else:
        state.state_type = state_type
        state.state_data = state_data or {}
        # 立即 flush 确保 UPDATE 语句被执行
        await session.flush()
        log.info(
            "state_updated",
            chat_id=chat_id,
            user_id=user_id,
            state_type=state_type,
        )
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
        # 立即 flush 确保 DELETE 语句被执行
        await session.flush()

