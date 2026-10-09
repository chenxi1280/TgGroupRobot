from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app import runtime
from backend.platform.runtime.leader_lock import LeaderLock


class _FailingScheduler:
    def __init__(self, app, **kwargs) -> None:
        self.app = app
        self.stop = AsyncMock()

    def register_tasks(self, tasks) -> None:
        _ = tasks

    async def start(self) -> None:
        raise RuntimeError("scheduler failed")


@pytest.mark.asyncio
async def test_partial_start_is_cleaned_up_when_scheduler_start_fails(monkeypatch) -> None:
    app = SimpleNamespace(
        bot_data={"settings": SimpleNamespace(), "db": object()},
        initialize=AsyncMock(),
        start=AsyncMock(),
        stop=AsyncMock(),
        shutdown=AsyncMock(),
        updater=SimpleNamespace(start_polling=AsyncMock(), stop=AsyncMock()),
    )
    leader = SimpleNamespace(start_monitor=lambda: None, release=AsyncMock())
    monkeypatch.setattr(runtime, "build_application", lambda: app)
    monkeypatch.setattr(runtime, "Scheduler", _FailingScheduler)
    monkeypatch.setattr(runtime, "_validate_schema_or_exit", AsyncMock())
    monkeypatch.setattr(runtime, "_acquire_leader_or_exit", AsyncMock(return_value=leader))

    with pytest.raises(RuntimeError, match="scheduler failed"):
        await runtime.run_bot_with_scheduler()

    app.updater.stop.assert_awaited_once()
    app.stop.assert_awaited_once()
    app.shutdown.assert_awaited_once()
    leader.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_leader_is_acquired_before_schema_readiness(monkeypatch) -> None:
    events: list[str] = []
    app = SimpleNamespace(
        bot_data={"settings": SimpleNamespace(), "db": object()},
        initialize=AsyncMock(side_effect=RuntimeError("stop after readiness")),
        updater=SimpleNamespace(),
    )
    leader = SimpleNamespace(start_monitor=lambda: None, release=AsyncMock())

    async def acquire(db):
        events.append("leader")
        return leader

    async def validate(app):
        events.append("schema")

    monkeypatch.setattr(runtime, "build_application", lambda: app)
    monkeypatch.setattr(runtime, "Scheduler", lambda app, **kwargs: SimpleNamespace())
    monkeypatch.setattr(runtime, "_acquire_leader_or_exit", acquire)
    monkeypatch.setattr(runtime, "_validate_schema_or_exit", validate)

    with pytest.raises(RuntimeError, match="stop after readiness"):
        await runtime.run_bot_with_scheduler()

    assert events == ["leader", "schema"]
    leader.release.assert_awaited_once()


class _ScalarResult:
    def scalar(self) -> bool:
        return True


class _LeaderConnection:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.commit = AsyncMock()
        self.close = AsyncMock()

    async def execute(self, statement, params=None):
        _ = statement, params
        self.execute_calls += 1
        if self.execute_calls > 1:
            raise ConnectionError("database connection lost")
        return _ScalarResult()


@pytest.mark.asyncio
async def test_leader_monitor_signals_connection_loss() -> None:
    connection = _LeaderConnection()
    engine = SimpleNamespace(connect=AsyncMock(return_value=connection))
    lock = LeaderLock(engine=engine)

    assert await lock.acquire(blocking=False) is True
    lock.start_monitor(interval_seconds=0)
    await asyncio.wait_for(lock.wait_until_lost(), timeout=0.2)

    assert lock.held is False
    assert connection.commit.await_count >= 1
    await lock.release()
