from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.features.verification import verification_join_guards
from backend.features.verification import welcome_delivery
from backend.shared import async_tasks
from backend.shared.services.publish_service import PublishResult, PublishService


@pytest.mark.asyncio
async def test_spawn_background_task_tracks_and_clears_completed_task():
    app = SimpleNamespace(bot_data={})

    async def _work():
        await asyncio.sleep(0)
        return "done"

    task = async_tasks.spawn_background_task(app, _work(), name="test.done")

    assert task in app.bot_data["_managed_background_tasks"]
    assert await task == "done"
    await asyncio.sleep(0)
    assert app.bot_data["_managed_background_tasks"] == set()


@pytest.mark.asyncio
async def test_cancel_background_tasks_cancels_pending_task():
    app = SimpleNamespace(bot_data={})
    cancelled = asyncio.Event()

    async def _work():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async_tasks.spawn_background_task(app, _work(), name="test.cancel")
    await asyncio.sleep(0)

    await async_tasks.cancel_background_tasks(app)

    assert cancelled.is_set()
    assert app.bot_data["_managed_background_tasks"] == set()


@pytest.mark.asyncio
async def test_publish_service_send_temporary_uses_managed_task(monkeypatch):
    scheduled: list[tuple[object, str | None]] = []

    async def fake_send(context, **kwargs):
        return PublishResult(ok=True, message_id=99)

    def fake_spawn(owner, awaitable, *, name=None):
        scheduled.append((owner, name))
        awaitable.close()
        return SimpleNamespace()

    monkeypatch.setattr(PublishService, "send", fake_send)
    monkeypatch.setattr("backend.shared.services.publish_service.spawn_background_task", fake_spawn)

    context = SimpleNamespace(bot=SimpleNamespace(), application=SimpleNamespace(bot_data={}))

    result = await PublishService.send_temporary(
        context,
        chat_id=-1001,
        text="hello",
        delete_after_seconds=30,
    )

    assert result.message_id == 99
    assert scheduled == [(context, "publish_service.delete_later")]


@pytest.mark.asyncio
async def test_join_notice_and_welcome_delete_use_managed_tasks(monkeypatch):
    scheduled: list[tuple[object, str | None]] = []

    class _Bot:
        async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None):
            return SimpleNamespace(delete=lambda: None)

    def fake_spawn(owner, awaitable, *, name=None):
        scheduled.append((owner, name))
        awaitable.close()
        return SimpleNamespace()

    monkeypatch.setattr("backend.features.verification.verification_join_guards.spawn_background_task", fake_spawn)
    monkeypatch.setattr("backend.features.verification.welcome_delivery.spawn_background_task", fake_spawn)

    context = SimpleNamespace(bot=_Bot(), application=SimpleNamespace(bot_data={}))

    await verification_join_guards.send_temporary_notice(
        context,
        -1001,
        "hello",
        delete_after_seconds=45,
    )

    session = SimpleNamespace(flush=lambda: None)

    async def _flush():
        return None

    session.flush = _flush
    welcome = SimpleNamespace(
        delete_mode="seconds",
        delete_delay_seconds=15,
        last_sent_message_id=None,
    )

    await welcome_delivery.apply_welcome_delete_strategy(session, welcome, 123, context, -1001)

    assert scheduled == [
        (context, "verification.cleanup_notice"),
        (context, "welcome_delivery.delete_later"),
    ]
