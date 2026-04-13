from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ConversationState
from backend.shared.services.base import ServiceBase
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.user_service import ensure_user

log = structlog.get_logger(__name__)


_EXPIRE_AT_KEY = "__expire_at__"


def _serialize_expire_at(expire_at: dt.datetime | None) -> str | None:
    if expire_at is None:
        return None
    if expire_at.tzinfo is None:
        expire_at = expire_at.replace(tzinfo=dt.UTC)
    return expire_at.astimezone(dt.UTC).isoformat()


def _parse_expire_at(state_data: dict[str, Any] | None) -> dt.datetime | None:
    if not isinstance(state_data, dict):
        return None
    raw = state_data.get(_EXPIRE_AT_KEY)
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _normalize_payload(
    state_data: dict[str, Any] | None,
    expire_at: dt.datetime | None,
) -> dict[str, Any]:
    payload = dict(state_data or {})
    if expire_at is None:
        payload.pop(_EXPIRE_AT_KEY, None)
        return payload
    payload[_EXPIRE_AT_KEY] = _serialize_expire_at(expire_at)
    return payload


class ConversationStateService:
    """
    统一对话状态服务。

    兼容旧函数式接口，同时提供 start/update/clear/get 四个入口。
    """

    @staticmethod
    async def get(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> ConversationState | None:
        state = await ServiceBase._get_by_filters(
            session,
            ConversationState,
            {"chat_id": chat_id, "user_id": user_id},
        )
        expire_at = _parse_expire_at(state.state_data) if state else None
        if state is not None and expire_at is not None and expire_at <= dt.datetime.now(dt.UTC):
            log.info(
                "conversation_state_expired",
                chat_id=chat_id,
                user_id=user_id,
                state_type=state.state_type,
                expire_at=expire_at.isoformat(),
            )
            await ServiceBase._delete_entity(session, state)
            return None

        log.info(
            "get_user_state_result",
            chat_id=chat_id,
            user_id=user_id,
            state_found=state is not None,
            state_type=state.state_type if state else None,
        )
        return state

    @classmethod
    async def _ensure_scope(
        cls,
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> None:
        await ensure_user(
            session,
            user_id=user_id,
            username=None,
            first_name=None,
            last_name=None,
            language_code=None,
        )
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            title=None,
        )

    @classmethod
    async def start(
        cls,
        session: AsyncSession,
        chat_id: int,
        user_id: int,
        state_type: str,
        state_data: dict | None = None,
        expire_at: dt.datetime | None = None,
    ) -> ConversationState:
        await cls._ensure_scope(session, chat_id=chat_id, user_id=user_id)

        state = await cls.get(session, chat_id, user_id)
        payload = _normalize_payload(state_data, expire_at)
        if state is None:
            state = ConversationState(
                chat_id=chat_id,
                user_id=user_id,
                state_type=state_type,
                state_data=payload,
            )
            session.add(state)
            await session.flush()
            log.info(
                "state_created_and_flushed",
                chat_id=chat_id,
                user_id=user_id,
                state_type=state_type,
            )
            return state

        await ServiceBase._update_entity(
            session,
            state,
            {
                "state_type": state_type,
                "state_data": payload,
                "updated_at": dt.datetime.now(dt.UTC),
            },
        )
        log.info(
            "state_updated",
            chat_id=chat_id,
            user_id=user_id,
            state_type=state_type,
        )
        return state

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        chat_id: int,
        user_id: int,
        *,
        state_type: str | None = None,
        state_data: dict | None = None,
        merge: bool = True,
        expire_at: dt.datetime | None = None,
    ) -> ConversationState | None:
        state = await cls.get(session, chat_id, user_id)
        if state is None:
            if state_type is None:
                return None
            return await cls.start(
                session,
                chat_id=chat_id,
                user_id=user_id,
                state_type=state_type,
                state_data=state_data,
                expire_at=expire_at,
            )

        new_state_data = state.state_data or {}
        if state_data is not None:
            new_state_data = {**new_state_data, **state_data} if merge else state_data
        if expire_at is not None:
            new_state_data = _normalize_payload(new_state_data, expire_at)

        updates: dict[str, object] = {"updated_at": dt.datetime.now(dt.UTC)}
        if state_type is not None:
            updates["state_type"] = state_type
        if state_data is not None:
            updates["state_data"] = new_state_data
        elif expire_at is not None:
            updates["state_data"] = new_state_data

        await ServiceBase._update_entity(session, state, updates)
        log.info(
            "state_updated",
            chat_id=chat_id,
            user_id=user_id,
            state_type=state.state_type,
        )
        return state

    @staticmethod
    async def clear(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> None:
        state = await ConversationStateService.get(session, chat_id, user_id)
        if state is not None:
            await ServiceBase._delete_entity(session, state)


async def get_user_state(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> ConversationState | None:
    return await ConversationStateService.get(session, chat_id, user_id)


async def set_user_state(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    state_type: str,
    state_data: dict | None = None,
    expire_at: dt.datetime | None = None,
) -> ConversationState:
    return await ConversationStateService.start(
        session,
        chat_id,
        user_id,
        state_type,
        state_data,
        expire_at=expire_at,
    )


async def clear_user_state(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> None:
    await ConversationStateService.clear(session, chat_id, user_id)
