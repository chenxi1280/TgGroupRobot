from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.scheduler.tasks.scheduled_message_task import ScheduledMessageTaskRunner
from backend.shared.services.base import ValidationError


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.active = False
        self.active_events: list[bool] = []

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self):
        self.session.active = True
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.session.active = False
        return False


class _Db:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def session_factory(self):
        return _SessionContext(self.session)


class _Bot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.next_message_id = 100

    def _message(self):
        self.next_message_id += 1
        return SimpleNamespace(message_id=self.next_message_id)

    async def delete_message(self, *args, **kwargs):
        self.calls.append(("delete_message", args, kwargs))
        return True

    async def pin_chat_message(self, *args, **kwargs):
        self.calls.append(("pin_chat_message", args, kwargs))
        return True

    async def send_message(self, *args, **kwargs):
        if hasattr(self, "session"):
            self.session.active_events.append(self.session.active)
        self.calls.append(("send_message", args, kwargs))
        return self._message()

    async def send_photo(self, *args, **kwargs):
        self.calls.append(("send_photo", args, kwargs))
        return self._message()

    async def send_video(self, *args, **kwargs):
        self.calls.append(("send_video", args, kwargs))
        return self._message()

    async def send_document(self, *args, **kwargs):
        self.calls.append(("send_document", args, kwargs))
        return self._message()

    async def send_sticker(self, *args, **kwargs):
        self.calls.append(("send_sticker", args, kwargs))
        return self._message()

    async def send_animation(self, *args, **kwargs):
        self.calls.append(("send_animation", args, kwargs))
        return self._message()


def _task(**kwargs):
    defaults = {
        "task_id": "task-1",
        "title": "测试任务",
        "chat_id": -1001,
        "enabled": True,
        "repeat_interval_min": 60,
        "start_at": None,
        "end_at": None,
        "day_start_hour": 0,
        "day_end_hour": 23,
        "delete_previous": False,
        "last_sent_message_id": None,
        "pin_message": False,
        "text": None,
        "parse_mode": "HTML",
        "media_type": "none",
        "media_file_id": None,
        "buttons": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_execute_disables_empty_task_without_sending_or_deleting(monkeypatch):
    session = _Session()
    bot = _Bot()
    task = _task(delete_previous=True, last_sent_message_id=88, pin_message=True)
    marked_sent: list[tuple[str, int]] = []

    async def fake_get_due_tasks(session_obj, limit: int = 100):
        return [task]

    async def fake_mark_sent(session_obj, task_id: str, message_id: int):
        marked_sent.append((task_id, message_id))
        return task

    monkeypatch.setattr(ScheduledMessageService, "get_due_tasks", staticmethod(fake_get_due_tasks))
    monkeypatch.setattr(ScheduledMessageService, "mark_task_sent", staticmethod(fake_mark_sent))

    app = SimpleNamespace(bot=bot, bot_data={"db": _Db(session)})

    await ScheduledMessageTaskRunner().execute(app)

    assert bot.calls == []
    assert task.enabled is False
    assert marked_sent == []
    assert session.commits == 1


@pytest.mark.asyncio
async def test_send_message_returns_none_for_empty_task_without_placeholder():
    bot = _Bot()
    app = SimpleNamespace(bot=bot)

    result = await ScheduledMessageTaskRunner()._send_message(app, _task())

    assert result is None
    assert bot.calls == []


@pytest.mark.asyncio
async def test_send_message_text_task_sends_one_text_message():
    bot = _Bot()
    app = SimpleNamespace(bot=bot)

    message_id = await ScheduledMessageTaskRunner()._send_message(app, _task(text="你好"))

    assert message_id == 101
    assert [(name, kwargs["text"]) for name, _, kwargs in bot.calls] == [("send_message", "你好")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "method_name"),
    [
        ("photo", "send_photo"),
        ("video", "send_video"),
        ("document", "send_document"),
        ("animation", "send_animation"),
    ],
)
async def test_send_message_media_task_sends_one_media_message(media_type: str, method_name: str):
    bot = _Bot()
    app = SimpleNamespace(bot=bot)

    message_id = await ScheduledMessageTaskRunner()._send_message(
        app,
        _task(text="caption", media_type=media_type, media_file_id=f"{media_type}-file"),
    )

    assert message_id == 101
    assert [name for name, _, _ in bot.calls] == [method_name]
    assert bot.calls[0][2]["caption"] == "caption"


@pytest.mark.asyncio
async def test_send_message_sticker_task_sends_one_sticker_without_text_fallback():
    bot = _Bot()
    app = SimpleNamespace(bot=bot)

    message_id = await ScheduledMessageTaskRunner()._send_message(
        app,
        _task(text="", media_type="sticker", media_file_id="sticker-file"),
    )

    assert message_id == 101
    assert [name for name, _, _ in bot.calls] == ["send_sticker"]


@pytest.mark.asyncio
async def test_execute_sends_after_claim_session_is_closed(monkeypatch):
    session = _Session()
    bot = _Bot()
    bot.session = session
    task = _task(text="你好")
    marked_sent: list[tuple[str, int]] = []

    async def fake_get_due_tasks(session_obj, limit: int = 100):
        return [task]

    async def fake_mark_sent(session_obj, task_id: str, message_id: int):
        marked_sent.append((task_id, message_id))
        return task

    monkeypatch.setattr(ScheduledMessageService, "get_due_tasks", staticmethod(fake_get_due_tasks))
    monkeypatch.setattr(ScheduledMessageService, "mark_task_sent", staticmethod(fake_mark_sent))

    app = SimpleNamespace(bot=bot, bot_data={"db": _Db(session)})

    await ScheduledMessageTaskRunner().execute(app)

    assert [name for name, _, _ in bot.calls] == ["send_message"]
    assert session.active_events == [False]
    assert marked_sent == [("task-1", 101)]
    assert session.commits == 2


@pytest.mark.asyncio
async def test_toggle_task_enabled_rejects_empty_task(monkeypatch):
    task = _task(enabled=False)

    async def fake_get_task(session_obj, task_id: str):
        return task

    monkeypatch.setattr(ScheduledMessageService, "get_task_by_id_or_404", staticmethod(fake_get_task))

    with pytest.raises(ValidationError):
        await ScheduledMessageService.toggle_task_enabled(_Session(), "task-1", True)
