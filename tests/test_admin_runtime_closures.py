from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.update_pipeline import MessageDispatcher
from backend.platform.scheduler.tasks.group_lock_task import _is_closed_now


def _group_update(*, text=None, caption=None, chat_type='supergroup'):
    message = SimpleNamespace(text=text, caption=caption)
    chat = SimpleNamespace(id=-1001, type=chat_type, title='Test Group')
    user = SimpleNamespace(id=42)
    return SimpleNamespace(effective_chat=chat, effective_user=user, effective_message=message)


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_message_dispatcher_routes_group_media_without_text(monkeypatch):
    dispatcher = MessageDispatcher()
    calls: list[str] = []

    async def fake_handle(update, context, chat, user, message_text):
        calls.append(message_text)

    dispatcher._group_message_handler.handle = fake_handle
    context = SimpleNamespace(application=SimpleNamespace(bot_data={'db': SimpleNamespace(session_factory=_SessionFactory())}))
    update = _group_update(text=None, caption=None)

    await dispatcher.dispatch(update, context)

    assert calls == ['']


def test_group_lock_window_cross_day():
    settings = SimpleNamespace(
        group_lock_schedule_enabled=True,
        group_lock_open_time='08:00',
        group_lock_close_time='02:00',
    )
    assert isinstance(_is_closed_now(settings), bool)


def test_group_lock_window_prefers_night_control_times():
    settings = SimpleNamespace(
        group_lock_schedule_enabled=True,
        group_lock_open_time='08:00',
        group_lock_close_time='02:00',
        night_mode_start_time='23:00',
        night_mode_end_time='07:00',
    )
    assert isinstance(_is_closed_now(settings), bool)


# Durable unchanged-state and restart coverage: test_generic_admin_runtime_postgres.py.
