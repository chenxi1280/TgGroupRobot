"""按 chat / user 分片串行，跨会话并行。"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator

from telegram import Update

from backend.platform.runtime.request_scope import bind_request_scope


class ChatShardLockManager:
    """为同一 shard key 串行执行，避免同群/同用户配置状态竞态。"""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._guard = asyncio.Lock()

    def shard_key_for_update(self, update: Update) -> str:
        chat = update.effective_chat
        user = update.effective_user
        if chat is not None and chat.type == "private" and user is not None:
            return f"private:{user.id}"
        if chat is not None:
            return f"chat:{chat.id}"
        if user is not None:
            return f"user:{user.id}"
        return f"update:{getattr(update, 'update_id', 0)}"

    async def acquire(self, key: str) -> asyncio.Lock:
        async with self._guard:
            return self._locks[key]

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        lock = await self.acquire(key)
        async with lock:
            yield


_MANAGER = ChatShardLockManager()


def get_chat_shard_manager() -> ChatShardLockManager:
    return _MANAGER


def install_chat_sharded_processing(application) -> None:
    """包装 Application.process_update：同 shard 串行，并绑定 RequestScope。"""
    if getattr(application, "_chat_shard_installed", False):
        return
    original = getattr(application, "process_update", None)
    if not callable(original):
        return

    manager = get_chat_shard_manager()

    async def process_update(update: Update, *args, **kwargs):
        key = manager.shard_key_for_update(update)
        chat = update.effective_chat
        user = update.effective_user
        async with manager.hold(key):
            async with bind_request_scope(
                update_id=getattr(update, "update_id", None),
                chat_id=chat.id if chat is not None else None,
                user_id=user.id if user is not None else None,
            ):
                return await original(update, *args, **kwargs)

    application.process_update = process_update  # type: ignore[method-assign]
    application._chat_shard_installed = True
