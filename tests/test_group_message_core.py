from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.group_ops.group_hooks import core as core_hooks


class _FakeSession:
    def __init__(self) -> None:
        self.get_calls: list[tuple[object, int]] = []
        self.commit_count = 0

    async def get(self, model, entity_id: int):
        self.get_calls.append((model, entity_id))
        return None

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _context(session: _FakeSession):
    return SimpleNamespace(application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_FakeSessionFactory(session))}))


def _settings():
    return SimpleNamespace(
        group_lock_schedule_enabled=False,
        group_lock_phrase_enabled=False,
        night_mode_enabled=False,
        name_change_monitor_enabled=False,
    )


async def _false(*args, **kwargs):
    return False


async def _true(*args, **kwargs):
    return True


@pytest.mark.asyncio
async def test_unified_group_handler_processes_auto_reply_for_normal_user(monkeypatch):
    session = _FakeSession()
    ensure_calls: list[dict] = []
    auto_reply_calls: list[tuple[int, str]] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        ensure_calls.append({"chat_id": chat_id, **kwargs})
        return _settings()

    async def fake_is_admin(context, chat_id: int, user_id: int):
        assert user_id == 42
        return False

    async def fake_auto_reply(context, db, chat, message, message_text: str):
        auto_reply_calls.append((chat.id, message_text))

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", fake_is_admin)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", _false)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", _false)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", _true)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", _false)
    monkeypatch.setattr(core_hooks, "_process_garage_features", _false)
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", _false)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", fake_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
        effective_message=SimpleNamespace(text="你好", caption=None, message_id=10, sender_chat=None),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is False
    assert session.get_calls and session.get_calls[0][1] == 42
    assert ensure_calls[0]["user_id"] == 42
    assert auto_reply_calls == [(-1001, "你好")]


@pytest.mark.asyncio
async def test_unified_group_handler_skips_auto_reply_for_auction_trigger(monkeypatch):
    session = _FakeSession()
    auto_reply_calls: list[tuple[int, str]] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        return _settings()

    async def fake_is_admin(context, chat_id: int, user_id: int):
        return False

    async def fake_auto_reply(context, db, chat, message, message_text: str):
        auto_reply_calls.append((chat.id, message_text))

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", fake_is_admin)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", _false)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", _false)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", _true)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", _false)
    monkeypatch.setattr(core_hooks, "_process_garage_features", _false)
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", _false)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", fake_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
        effective_message=SimpleNamespace(text="💰 拍卖", caption=None, message_id=10, sender_chat=None),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is False
    assert auto_reply_calls == []


@pytest.mark.asyncio
async def test_unified_group_handler_sender_chat_skips_user_checks_but_runs_auto_reply(monkeypatch):
    session = _FakeSession()
    ensure_calls: list[dict] = []
    auto_reply_calls: list[tuple[int, str]] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        ensure_calls.append({"chat_id": chat_id, **kwargs})
        return _settings()

    async def forbidden_user_check(*args, **kwargs):
        raise AssertionError("sender_chat messages must skip real-user checks")

    async def fake_auto_reply(context, db, chat, message, message_text: str):
        auto_reply_calls.append((chat.id, message_text))

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_garage_features", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", fake_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=None,
        effective_message=SimpleNamespace(
            text="你好",
            caption=None,
            message_id=10,
            sender_chat=SimpleNamespace(id=-100777, title="Channel Identity", username="channel_identity"),
        ),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is False
    assert session.get_calls == []
    assert ensure_calls[0]["user_id"] is None
    assert auto_reply_calls == [(-1001, "你好")]


@pytest.mark.asyncio
async def test_unified_group_handler_skips_force_subscribe_for_admin(monkeypatch):
    session = _FakeSession()
    auto_reply_calls: list[tuple[int, str]] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        return _settings()

    async def fake_is_admin(context, chat_id: int, user_id: int):
        return True

    async def forbidden_force_subscribe(*args, **kwargs):
        raise AssertionError("admins should be exempt from force subscribe checks")

    async def fake_auto_reply(context, db, chat, message, message_text: str):
        auto_reply_calls.append((chat.id, message_text))

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", fake_is_admin)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", _false)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_reply_ban", _false)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", forbidden_force_subscribe)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", forbidden_force_subscribe)
    monkeypatch.setattr(core_hooks, "_process_garage_features", _false)
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", forbidden_force_subscribe)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", fake_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
        effective_message=SimpleNamespace(text="管理员发言", caption=None, message_id=10, sender_chat=None),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is False
    assert auto_reply_calls == [(-1001, "管理员发言")]
