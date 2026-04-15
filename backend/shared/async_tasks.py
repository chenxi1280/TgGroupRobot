from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable
from typing import Any

import structlog

_TASKS_KEY = "_managed_background_tasks"
_GLOBAL_TASKS: weakref.WeakSet[asyncio.Task[Any]] = weakref.WeakSet()

log = structlog.get_logger(__name__)


def _resolve_application(owner: object | None) -> object | None:
    if owner is None:
        return None
    if hasattr(owner, "bot_data"):
        return owner
    return getattr(owner, "application", None)


def _get_task_bucket(owner: object | None) -> set[asyncio.Task[Any]] | None:
    application = _resolve_application(owner)
    if application is None:
        return None
    return application.bot_data.setdefault(_TASKS_KEY, set())


def spawn_background_task(
    owner: object | None,
    awaitable: Awaitable[Any],
    *,
    name: str | None = None,
) -> asyncio.Task[Any]:
    task = asyncio.create_task(awaitable, name=name)
    bucket = _get_task_bucket(owner)
    if bucket is not None:
        bucket.add(task)
    _GLOBAL_TASKS.add(task)

    def _finalize(done_task: asyncio.Task[Any]) -> None:
        if bucket is not None:
            bucket.discard(done_task)
        try:
            _GLOBAL_TASKS.discard(done_task)
        except KeyError:
            pass
        try:
            done_task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            log.warning(
                "background_task_failed",
                task_name=done_task.get_name(),
                error=str(exc),
            )

    task.add_done_callback(_finalize)
    return task


async def cancel_background_tasks(owner: object | None = None) -> None:
    current = asyncio.current_task()
    bucket = _get_task_bucket(owner)
    tasks = list(bucket) if bucket is not None else list(_GLOBAL_TASKS)
    pending: list[asyncio.Task[Any]] = []
    for task in tasks:
        if task is current or task.done():
            if bucket is not None:
                bucket.discard(task)
            continue
        if task.get_loop() is not asyncio.get_running_loop():
            continue
        task.cancel()
        pending.append(task)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if bucket is not None:
        bucket.clear()
