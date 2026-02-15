from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import admin_handler


@pytest.mark.asyncio
async def test_admin_callback_handles_two_part_action_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    class _Q:
        data = "adm:switch_group"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": 0}
