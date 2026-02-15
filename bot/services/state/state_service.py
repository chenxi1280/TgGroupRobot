from __future__ import annotations

import structlog

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ConversationState, TgChat
from bot.services.base import ServiceBase
from bot.services.core.user_service import ensure_user

log = structlog.get_logger(__name__)


async def get_user_state(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> ConversationState | None:
    """
    获取用户的当前对话状态

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        user_id: 用户 ID

    Returns:
        对话状态对象，如果不存在则返回 None
    """
    state = await ServiceBase._get_by_filters(
        session,
        ConversationState,
        {"chat_id": chat_id, "user_id": user_id},
    )
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
    """
    设置用户的对话状态

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        user_id: 用户 ID
        state_type: 状态类型
        state_data: 状态数据

    Returns:
        对话状态对象
    """
    # 外键自愈：conversation_states 依赖 tg_users/tg_chats
    await ensure_user(
        session,
        user_id=user_id,
        username=None,
        first_name=None,
        last_name=None,
        language_code=None,
    )
    chat = await ServiceBase._get_by_id(session, TgChat, chat_id)
    if chat is None:
        inferred_type = "supergroup" if chat_id < 0 else "private"
        session.add(TgChat(id=chat_id, type=inferred_type, title=None))
        await session.flush()

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
        await ServiceBase._update_entity(
            session,
            state,
            {"state_type": state_type, "state_data": state_data or {}},
        )
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
    """
    清除用户的对话状态

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        user_id: 用户 ID
    """
    state = await get_user_state(session, chat_id, user_id)
    if state is not None:
        await ServiceBase._delete_entity(session, state)
