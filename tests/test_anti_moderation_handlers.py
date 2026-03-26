from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

import bot.handlers.anti_flood_handler as anti_flood_handler
import bot.handlers.anti_spam_handler as anti_spam_handler
from bot.services.moderation.anti_spam_service import SpamViolation


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _SessionFactory:
    def __init__(self, session: _Session) -> None:
        self._session = session

    def __call__(self) -> "_SessionFactory":
        return self

    async def __aenter__(self) -> _Session:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeUser:
    def __init__(self, user_id: int = 123) -> None:
        self.id = user_id
        self.username = "tester"
        self.first_name = "Test"
        self.last_name = "User"
        self.language_code = "zh"
        self.is_bot = False

    def mention_html(self) -> str:
        return "<a href='tg://user?id=123'>tester</a>"


def _build_update(chat_id: int = -100, message_id: int = 42):
    user = _FakeUser()
    chat = SimpleNamespace(id=chat_id, type="supergroup", title="Test Chat")
    message = SimpleNamespace(message_id=message_id, sender_chat=None)
    return SimpleNamespace(effective_chat=chat, effective_message=message, effective_user=user)


def _build_context(session: _Session):
    db = SimpleNamespace(session_factory=_SessionFactory(session))
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": db}),
        bot=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_anti_spam_handler_records_final_action(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)
    recorded: list[dict[str, object]] = []
    executed: list[dict[str, object]] = []

    settings = SimpleNamespace(
        anti_spam_enabled=True,
        anti_spam_action="mute",
        anti_spam_mute_duration=600,
        anti_spam_exempt_admin=False,
        anti_spam_delete_notify=False,
        anti_spam_delete_notify_seconds=30,
    )

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_detect_spam_violation(*args, **kwargs):
        return SpamViolation(blocked=True, rule="spam", detail="hit")

    async def fake_resolve_effective_action(*args, **kwargs):
        return SimpleNamespace(action="delete", fallback_reason="downgraded")

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    monkeypatch.setattr(
        anti_spam_handler,
        "get_chat_settings",
        fake_get_chat_settings,
    )
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "detect_spam_violation", fake_detect_spam_violation)
    monkeypatch.setattr(anti_spam_handler, "resolve_effective_action", fake_resolve_effective_action)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)

    async def fake_record_violation(session, **kwargs):
        recorded.append(kwargs)

    async def fake_execute_spam_punishment(*args, **kwargs):
        executed.append({"args": args, "kwargs": kwargs})
        return True

    async def fake_send_temporary_notice(*args, **kwargs):
        return None

    monkeypatch.setattr(anti_spam_handler, "record_violation", fake_record_violation)
    monkeypatch.setattr(anti_spam_handler, "execute_spam_punishment", fake_execute_spam_punishment)
    monkeypatch.setattr(anti_spam_handler, "send_temporary_notice", fake_send_temporary_notice)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert recorded[0]["action"] == "delete"
    assert executed[0]["args"][3] == "delete"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_anti_flood_handler_records_final_action(monkeypatch):
    session = _Session()
    update = _build_update(message_id=88)
    context = _build_context(session)
    recorded: list[dict[str, object]] = []
    executed: list[dict[str, object]] = []

    settings = SimpleNamespace(
        anti_flood_enabled=True,
        anti_flood_messages=3,
        anti_flood_seconds=10,
        anti_flood_action="mute",
        anti_flood_mute_duration=600,
        anti_flood_exempt_admin=False,
        anti_flood_cleanup_messages=False,
        anti_flood_delete_notify=False,
        anti_flood_delete_notify_seconds=30,
    )

    class FakeTracker:
        async def add_message(self, *args, **kwargs):
            return None

        async def check_flood(self, *args, **kwargs):
            return SimpleNamespace(is_flooding=True, message_count=4, time_span=3.2, action="none")

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_resolve_effective_action(*args, **kwargs):
        return SimpleNamespace(action="delete", fallback_reason="downgraded")

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    monkeypatch.setattr(anti_flood_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_flood_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_flood_handler, "get_tracker", lambda: FakeTracker())
    monkeypatch.setattr(anti_flood_handler, "resolve_effective_action", fake_resolve_effective_action)
    monkeypatch.setattr(anti_flood_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_flood_handler, "ensure_user", fake_ensure_user)

    async def fake_record_violation(session, **kwargs):
        recorded.append(kwargs)

    async def fake_execute_flood_punishment(*args, **kwargs):
        executed.append({"args": args, "kwargs": kwargs})
        return True

    async def fake_send_temporary_notice(*args, **kwargs):
        return None

    monkeypatch.setattr(anti_flood_handler, "record_violation", fake_record_violation)
    monkeypatch.setattr(anti_flood_handler, "execute_flood_punishment", fake_execute_flood_punishment)
    monkeypatch.setattr(anti_flood_handler, "send_temporary_notice", fake_send_temporary_notice)

    with pytest.raises(ApplicationHandlerStop):
        await anti_flood_handler.anti_flood_message_handler(update, context)

    assert recorded[0]["action"] == "delete"
    assert executed[0]["args"][3] == "delete"
    assert session.commits == 2
