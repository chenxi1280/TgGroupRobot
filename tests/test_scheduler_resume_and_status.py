from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.platform.scheduler.core.core import ScheduledTask, Scheduler


class _FailingTask(ScheduledTask):
    async def execute(self, app) -> None:
        raise RuntimeError("boom")


class _BrokenSession:
    async def __aenter__(self):
        raise RuntimeError("scheduler state unavailable")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BrokenDb:
    def session_factory(self):
        return _BrokenSession()


@pytest.mark.asyncio
async def test_task_auto_pauses_and_exposes_status() -> None:
    task = _FailingTask(name="fragile", interval=60, max_consecutive_failures=2)

    await task.run(SimpleNamespace())
    assert task.enabled is True
    assert task.error_count == 1

    await task.run(SimpleNamespace())
    assert task.enabled is False
    assert task.auto_paused is True
    status = task.get_status()
    assert status["auto_paused"] is True
    assert status["paused_reason"]


def test_scheduler_resume_task() -> None:
    task = _FailingTask(name="fragile", interval=60)
    task.enabled = False
    task.auto_paused = True
    task.paused_reason = "paused"
    task.error_count = 9

    scheduler = Scheduler(SimpleNamespace(bot_data={}))
    scheduler.register_task(task)
    assert scheduler.resume_task("fragile") is True
    assert task.enabled is True
    assert task.auto_paused is False
    assert task.error_count == 0


@pytest.mark.asyncio
async def test_scheduler_start_fails_when_persisted_state_cannot_be_loaded() -> None:
    scheduler = Scheduler(SimpleNamespace(bot_data={"db": _BrokenDb()}))
    scheduler.register_task(_FailingTask(name="fragile", interval=60))

    with pytest.raises(RuntimeError, match="scheduler state unavailable"):
        await scheduler.start()

    assert scheduler.running is False


@pytest.mark.asyncio
async def test_auto_pause_surfaces_required_persistence_failure(monkeypatch) -> None:
    task = _FailingTask(name="fragile", interval=60, max_consecutive_failures=1)
    app = SimpleNamespace(bot_data={"db": object()})

    async def fail_persist(db, current_task):
        _ = db, current_task
        raise RuntimeError("pause state unavailable")

    monkeypatch.setattr(
        "backend.platform.scheduler.core.persistence.persist_task_snapshot",
        fail_persist,
    )

    with pytest.raises(RuntimeError, match="pause state unavailable"):
        await task.run(app)

    assert task.enabled is False
    assert task.auto_paused is True
