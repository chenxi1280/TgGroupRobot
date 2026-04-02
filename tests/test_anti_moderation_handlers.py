from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

import bot.handlers.banned_word_handler as banned_word_handler
import bot.handlers.anti_flood_handler as anti_flood_handler
import bot.handlers.anti_spam_handler as anti_spam_handler
from bot.services.moderation import banned_word_service
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


@pytest.mark.asyncio
async def test_banned_word_toggle_and_delete_are_chat_scoped(monkeypatch):
    session = _Session()
    update = _build_update(chat_id=-100123)
    context = _build_context(session)

    class _Q:
        data = "banned_word_delete_12:-100123"

        def __init__(self) -> None:
            self.answers: list[tuple[str, bool]] = []
            self.edits: list[str] = []

        async def answer(self, text: str = "", show_alert: bool = False) -> None:
            self.answers.append((text, show_alert))

        async def edit_message_text(self, text: str, reply_markup=None, parse_mode=None) -> None:
            self.edits.append(text)

    q = _Q()
    update.callback_query = q

    deleted_calls: list[dict[str, object]] = []
    toggled_calls: list[dict[str, object]] = []

    async def fake_delete_banned_word(session, word_id: int, *, chat_id: int | None = None):
        deleted_calls.append({"word_id": word_id, "chat_id": chat_id})
        return True

    async def fake_toggle_banned_word(session, word_id: int, *, chat_id: int | None = None):
        toggled_calls.append({"word_id": word_id, "chat_id": chat_id})
        return True

    async def fake_get_chat_banned_words(session, chat_id: int, active_only: bool = False):
        assert chat_id == -100123
        return []

    async def fake_get_trigger_stats(session, chat_id: int):
        assert chat_id == -100123
        return 0

    async def fake_is_user_admin(*args, **kwargs):
        return True

    monkeypatch.setattr(banned_word_handler, "delete_banned_word", fake_delete_banned_word)
    monkeypatch.setattr(banned_word_handler, "toggle_banned_word", fake_toggle_banned_word)
    monkeypatch.setattr(banned_word_handler, "get_chat_banned_words", fake_get_chat_banned_words)
    monkeypatch.setattr(banned_word_handler, "get_trigger_stats", fake_get_trigger_stats)
    monkeypatch.setattr(banned_word_handler, "is_user_admin", fake_is_user_admin)
    async def fake_require_current_chat(*args, **kwargs):
        return -100123

    monkeypatch.setattr(banned_word_handler.PrivateChatContext, "require_current_chat", fake_require_current_chat)

    async def fake_get_banned_word_in_chat(session, chat_id: int, word_id: int):
        assert chat_id == -100123
        assert word_id == 12
        return SimpleNamespace(id=12, chat_id=chat_id, is_active=True, word="bad", match_type="contains", action="delete", notify=True)

    monkeypatch.setattr(banned_word_service, "get_banned_word_in_chat", fake_get_banned_word_in_chat)

    await banned_word_handler.banned_word_delete_callback(update, context)
    assert deleted_calls == [{"word_id": 12, "chat_id": -100123}]
    assert q.answers == [("违禁词已删除", False)]
    assert q.edits

    toggle = banned_word_handler.BannedWordToggleHandler()

    async def fake_toggle_scoped(session, word_id: int, *, chat_id: int | None = None):
        toggled_calls.append({"word_id": word_id, "chat_id": chat_id})
        return True

    monkeypatch.setattr(banned_word_handler, "toggle_banned_word", fake_toggle_scoped)
    await toggle._toggle_word(context, 12, -100123)

    assert toggled_calls == [{"word_id": 12, "chat_id": -100123}]


@pytest.mark.asyncio
async def test_banned_word_service_toggle_delete_use_chat_scope(monkeypatch):
    scoped_calls: list[tuple[str, int, int]] = []

    async def fake_get_banned_word_in_chat(session, chat_id: int, word_id: int):
        scoped_calls.append(("get", chat_id, word_id))
        return SimpleNamespace(id=word_id, chat_id=chat_id, is_active=True)

    async def fake_delete(session, entity):
        scoped_calls.append(("delete", entity.chat_id, entity.id))

    async def fake_update(session, entity, updates):
        scoped_calls.append(("update", entity.chat_id, entity.id))

    monkeypatch.setattr(banned_word_service, "get_banned_word_in_chat", fake_get_banned_word_in_chat)
    monkeypatch.setattr(banned_word_service.ServiceBase, "_delete_entity", fake_delete)
    monkeypatch.setattr(banned_word_service.ServiceBase, "_update_entity", fake_update)

    toggle_result = await banned_word_service.toggle_banned_word(None, 7, chat_id=-100123)
    delete_result = await banned_word_service.delete_banned_word(None, 8, chat_id=-100123)

    assert toggle_result is True
    assert delete_result is True
    assert scoped_calls == [
        ("get", -100123, 7),
        ("update", -100123, 7),
        ("get", -100123, 8),
        ("delete", -100123, 8),
    ]
