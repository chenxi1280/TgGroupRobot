"""状态管理工具类

提供统一的状态管理接口，简化 Handler 中的状态操作。
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ConversationState
from backend.platform.state.state_service import (
    clear_user_state as service_clear_state,
    get_user_state as service_get_state,
    set_user_state as service_set_state,
)

log = structlog.get_logger(__name__)


class StateHelper:
    """状态管理工具类

    封装状态管理操作，提供更简洁的接口。
    """

    def __init__(self, session: AsyncSession, chat_id: int, user_id: int) -> None:
        """初始化状态助手

        Args:
            session: 数据库会话
            chat_id: 聊天 ID（群组或私聊）
            user_id: 用户 ID
        """
        self.session = session
        self.chat_id = chat_id
        self.user_id = user_id

    async def get_state(self) -> ConversationState | None:
        """获取当前状态

        Returns:
            ConversationState | None: 当前状态，如果不存在返回 None
        """
        return await service_get_state(self.session, self.chat_id, self.user_id)

    async def set_state(
        self,
        state_type: str,
        state_data: dict | None = None,
    ) -> ConversationState:
        """设置状态

        Args:
            state_type: 状态类型
            state_data: 状态数据（可选）

        Returns:
            ConversationState: 设置后的状态对象
        """
        return await service_set_state(
            self.session,
            self.chat_id,
            self.user_id,
            state_type,
            state_data,
        )

    async def clear_state(self) -> None:
        """清除当前状态"""
        await service_clear_state(self.session, self.chat_id, self.user_id)

    async def require_state(self, expected_type: str) -> ConversationState | None:
        """要求特定状态类型

        如果当前状态类型与期望不符，返回 None。

        Args:
            expected_type: 期望的状态类型

        Returns:
            ConversationState | None: 如果状态类型匹配返回状态对象，否则返回 None
        """
        state = await self.get_state()
        if state and state.state_type == expected_type:
            return state
        return None

    async def has_state(self) -> bool:
        """检查是否有状态

        Returns:
            bool: 是否存在状态
        """
        state = await self.get_state()
        return state is not None

    async def get_state_data(self, key: str, default=None):
        """获取状态数据中的特定键值

        Args:
            key: 数据键
            default: 默认值（如果键不存在）

        Returns:
            键对应的值或默认值
        """
        state = await self.get_state()
        if state and state.state_data:
            return state.state_data.get(key, default)
        return default

    async def update_state_data(self, updates: dict) -> ConversationState:
        """更新状态数据

        保留现有数据，只更新指定的键。

        Args:
            updates: 要更新的键值对

        Returns:
            ConversationState: 更新后的状态对象
        """
        state = await self.get_state()
        if state is None:
            raise ValueError("No state exists. Call set_state first.")

        if state.state_data is None:
            state.state_data = {}
        state.state_data.update(updates)

        await self.session.flush()
        return state

    @staticmethod
    async def get_state_by_chat(
        session: AsyncSession,
        chat,
        user_id: int,
    ) -> ConversationState | None:
        """根据聊天类型获取用户状态

        私聊使用 user.id 作为 chat_id，群聊使用 chat.id。

        Args:
            session: 数据库会话
            chat: 聊天对象（有 type 属性）
            user_id: 用户 ID

        Returns:
            ConversationState | None: 用户状态对象
        """
        state_chat_id = user_id if chat.type == "private" else chat.id
        return await service_get_state(session, state_chat_id, user_id)
