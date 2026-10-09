"""单次 Telegram update 内的请求作用域。

在同一条 update 处理链路中共享：
- settings / admin 判定缓存
- 可选的数据库 session
- 业务短路对积分的抑制标记
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.runtime.session import Database

_SCOPE: ContextVar["RequestScope | None"] = ContextVar("tg_request_scope", default=None)


@dataclass
class RequestScope:
    update_id: int | None = None
    chat_id: int | None = None
    user_id: int | None = None
    settings: Any | None = None
    is_admin: bool | None = None
    admin_checked: bool = False
    suppress_message_points: bool = False
    session: AsyncSession | None = None
    owns_session: bool = False
    cache: dict[str, Any] = field(default_factory=dict)

    def get_cached(self, key: str) -> Any | None:
        return self.cache.get(key)

    def set_cached(self, key: str, value: Any) -> Any:
        self.cache[key] = value
        return value


def current_scope() -> RequestScope | None:
    return _SCOPE.get()


def require_scope() -> RequestScope:
    scope = _SCOPE.get()
    if scope is None:
        scope = RequestScope()
        _SCOPE.set(scope)
    return scope


@asynccontextmanager
async def bind_request_scope(
    *,
    update_id: int | None = None,
    chat_id: int | None = None,
    user_id: int | None = None,
) -> AsyncIterator[RequestScope]:
    existing = _SCOPE.get()
    if existing is not None:
        # 同一 update 内重入：复用已有 scope，避免嵌套 reset 清掉外层
        if update_id is not None:
            existing.update_id = existing.update_id or update_id
        if chat_id is not None:
            existing.chat_id = existing.chat_id or chat_id
        if user_id is not None:
            existing.user_id = existing.user_id or user_id
        yield existing
        return

    scope = RequestScope(update_id=update_id, chat_id=chat_id, user_id=user_id)
    token: Token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        if scope.owns_session and scope.session is not None:
            await scope.session.close()
        _SCOPE.reset(token)


@asynccontextmanager
async def scoped_session(db: Database) -> AsyncIterator[AsyncSession]:
    """复用当前 request scope 的 session；没有 scope 时创建临时 session。"""
    scope = current_scope()
    if scope is not None and scope.session is not None:
        yield scope.session
        return

    async with db.session_factory() as session:
        if scope is not None:
            scope.session = session
            scope.owns_session = False
        try:
            yield session
        finally:
            if scope is not None and scope.session is session:
                scope.session = None


async def get_or_load_settings(
    db: Database,
    chat_id: int,
    *,
    loader=None,
) -> Any:
    """在 request scope 内缓存 chat settings。"""
    scope = current_scope()
    if scope is not None and scope.settings is not None and scope.chat_id == chat_id:
        return scope.settings

    if loader is None:
        from backend.shared.services.chat_service import get_chat_settings

        async def _default_loader(session: AsyncSession, target_chat_id: int):
            return await get_chat_settings(session, target_chat_id)

        loader = _default_loader

    async with scoped_session(db) as session:
        settings = await loader(session, chat_id)
        await session.commit()
    if scope is not None:
        scope.chat_id = chat_id
        scope.settings = settings
    return settings


async def get_or_load_admin(
    context: Any,
    chat_id: int,
    user_id: int | None,
    *,
    checker=None,
) -> bool:
    """在 request scope 内缓存管理员判定。"""
    if user_id is None or user_id <= 0:
        return False

    scope = current_scope()
    if (
        scope is not None
        and scope.admin_checked
        and scope.chat_id == chat_id
        and scope.user_id == user_id
        and scope.is_admin is not None
    ):
        return scope.is_admin

    if checker is None:
        from backend.shared.services.permission_service import is_user_admin

        checker = is_user_admin

    is_admin = bool(await checker(context, chat_id, user_id))
    if scope is not None:
        scope.chat_id = chat_id
        scope.user_id = user_id
        scope.is_admin = is_admin
        scope.admin_checked = True
    return is_admin


def mark_suppress_message_points(suppress: bool = True) -> None:
    scope = current_scope()
    if scope is not None:
        scope.suppress_message_points = suppress


def should_award_message_points() -> bool:
    scope = current_scope()
    if scope is None:
        return True
    return not scope.suppress_message_points
