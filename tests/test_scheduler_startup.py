from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest

from backend.platform.scheduler.core.core import Scheduler, ScheduledTask


class _RecordingTask(ScheduledTask):
    def __init__(self, name: str, interval: int, calls: list[str]) -> None:
        super().__init__(name=name, interval=interval)
        self.calls = calls

    async def execute(self, app) -> None:
        self.calls.append(self.name)


class _FailingTask(ScheduledTask):
    async def execute(self, app) -> None:
        raise RuntimeError("delivery batch failed")


@pytest.mark.asyncio
async def test_scheduler_defers_first_run_by_default() -> None:
    calls: list[str] = []
    task = _RecordingTask("demo", interval=60, calls=calls)
    scheduler = Scheduler(SimpleNamespace(), run_immediately=False)
    scheduler.register_task(task)

    before = dt.datetime.now(dt.timezone.utc)
    await scheduler.start()
    await asyncio.sleep(0)

    try:
        assert calls == []
        assert task.next_run is not None
        assert task.next_run >= before + dt.timedelta(seconds=59)
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_staggers_initial_runs() -> None:
    calls: list[str] = []
    first = _RecordingTask("first", interval=60, calls=calls)
    second = _RecordingTask("second", interval=60, calls=calls)
    scheduler = Scheduler(SimpleNamespace(), run_immediately=False, initial_stagger_seconds=2.0)
    scheduler.register_tasks([first, second])

    await scheduler.start()
    await asyncio.sleep(0)

    try:
        assert first.next_run is not None
        assert second.next_run is not None
        assert second.next_run - first.next_run >= dt.timedelta(seconds=1.9)
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_task_status_records_latest_success() -> None:
    task = _RecordingTask("success", interval=60, calls=[])

    await task.run(SimpleNamespace())

    status = task.get_status()
    assert status["last_success_at"] is not None
    assert status["last_failure_at"] is None
    assert status["last_error"] is None


@pytest.mark.asyncio
async def test_task_status_records_latest_failure() -> None:
    task = _FailingTask(name="failure", interval=60)

    await task.run(SimpleNamespace())

    status = task.get_status()
    assert status["last_success_at"] is None
    assert status["last_failure_at"] is not None
    assert status["last_error"] == "delivery batch failed"
