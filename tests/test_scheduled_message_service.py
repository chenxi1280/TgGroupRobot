from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services.base import NotFoundError
from bot.services.scheduled_message_service import ScheduledMessageService


@pytest.mark.asyncio
async def test_get_task_in_chat_or_404_accepts_matching_chat(monkeypatch):
    task = SimpleNamespace(chat_id=-1001, task_id="task-1")

    async def fake_get_task_by_id_or_404(session, task_id):
        assert task_id == "task-1"
        return task

    monkeypatch.setattr(
        ScheduledMessageService,
        "get_task_by_id_or_404",
        fake_get_task_by_id_or_404,
    )

    result = await ScheduledMessageService.get_task_in_chat_or_404(None, -1001, "task-1")

    assert result is task


@pytest.mark.asyncio
async def test_get_task_in_chat_or_404_rejects_cross_chat_task(monkeypatch):
    task = SimpleNamespace(chat_id=-1002, task_id="task-2")

    async def fake_get_task_by_id_or_404(session, task_id):
        assert task_id == "task-2"
        return task

    monkeypatch.setattr(
        ScheduledMessageService,
        "get_task_by_id_or_404",
        fake_get_task_by_id_or_404,
    )

    with pytest.raises(NotFoundError):
        await ScheduledMessageService.get_task_in_chat_or_404(None, -1001, "task-2")
