from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.garage import forward_operations


class FakeSession:
    async def commit(self) -> None:
        return None


class SessionContext:
    async def __aenter__(self):
        return FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeDb:
    def session_factory(self):
        return SessionContext()


@pytest.mark.asyncio
async def test_garage_failure_page_lists_retry_cancel_and_confirmed_replay(monkeypatch) -> None:
    show = getattr(admin_handler._admin_handler, "_show_garage_forward_tasks", None)
    assert show is not None
    rendered: dict[str, object] = {}

    async def fake_list(session, filters):
        return (
            SimpleNamespace(
                id=7,
                source_channel_id=-10001,
                source_message_id=321,
                status="permanent_failed",
                attempts=3,
                last_error="telegram_forbidden",
            ),
            SimpleNamespace(
                id=8,
                source_channel_id=-10002,
                source_message_id=322,
                status="uncertain",
                attempts=1,
                last_error="database_finalize_failed",
            ),
        )

    async def fake_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["rows"] = reply_markup.inline_keyboard

    monkeypatch.setattr(forward_operations, "list_garage_tasks", fake_list)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_edit)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": FakeDb()}))

    await show(SimpleNamespace(), context, chat_id=-20001)

    callbacks = [[button.callback_data for button in row] for row in rendered["rows"]]
    assert ["gfw:ops:-20001:retry:7", "gfw:ops:-20001:cancel:7"] in callbacks
    assert ["gfw:ops:-20001:replay:8", "gfw:ops:-20001:cancel:8"] in callbacks
    assert "database_finalize_failed" in rendered["text"]


@pytest.mark.asyncio
async def test_uncertain_replay_page_requires_second_confirmation(monkeypatch) -> None:
    rendered: dict[str, object] = {}

    async def fake_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["rows"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_edit)
    await admin_handler._admin_handler._show_garage_replay_confirmation(
        SimpleNamespace(),
        chat_id=-20001,
        delivery_id=8,
    )

    callbacks = [[button.callback_data for button in row] for row in rendered["rows"]]
    assert ["gfw:ops:-20001:replay_confirm:8"] in callbacks
    assert "可能产生重复" in rendered["text"]
