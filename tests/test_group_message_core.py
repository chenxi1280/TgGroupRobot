from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.group_ops.group_hooks import core as core_hooks
from backend.features.group_ops.group_hooks import moderation as moderation_hooks
from backend.features.moderation.services.garbage_guard_rules import set_rule_config
from backend.platform.telegram.group_pipeline import GroupMessageHandler


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


async def _reply_noop(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_alliance_reply_ban_uses_team_command(monkeypatch) -> None:
    session = _FakeSession()
    calls: list[dict] = []

    async def fake_get_member(session, chat_id: int):
        return SimpleNamespace(alliance_id=9)

    async def fake_execute_user_action(context, **kwargs):
        calls.append({"execute": kwargs})
        return SimpleNamespace(punishment_applied=True)

    async def fake_add_joint_ban_entry(session, **kwargs):
        calls.append({"joint_ban": kwargs})

    monkeypatch.setattr(moderation_hooks.AllianceService, "get_member", fake_get_member)
    monkeypatch.setattr(moderation_hooks, "execute_user_action", fake_execute_user_action)
    monkeypatch.setattr(moderation_hooks.AllianceService, "add_joint_ban_entry", fake_add_joint_ban_entry)
    context = _context(session)

    handled = await moderation_hooks._process_alliance_reply_ban(
        context,
        context.application.bot_data["db"],
        SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        SimpleNamespace(id=7),
        SimpleNamespace(
            reply_to_message=SimpleNamespace(
                message_id=41,
                from_user=SimpleNamespace(id=456),
                sender_chat=None,
            ),
            reply_text=_reply_noop,
        ),
        "team",
    )

    assert handled is True
    assert calls[0]["execute"]["user_id"] == 456
    assert calls[1]["joint_ban"]["reason"] == "reply_team_command"


@pytest.mark.asyncio
async def test_alliance_reply_ban_ignores_old_t_command(monkeypatch) -> None:
    async def forbidden_get_member(*args, **kwargs):
        raise AssertionError("old t command must not reach alliance lookup")

    monkeypatch.setattr(moderation_hooks.AllianceService, "get_member", forbidden_get_member)
    context = _context(_FakeSession())

    handled = await moderation_hooks._process_alliance_reply_ban(
        context,
        context.application.bot_data["db"],
        SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        SimpleNamespace(id=7),
        SimpleNamespace(reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=456))),
        "t",
    )

    assert handled is False


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
async def test_unified_group_handler_bottom_button_event_runs_before_auto_reply(monkeypatch):
    session = _FakeSession()
    bottom_button_calls: list[tuple[int, str]] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        return _settings()

    async def fake_is_admin(context, chat_id: int, user_id: int):
        return False

    async def fake_bottom_button_trigger(update, context, chat_id: int, message_text: str):
        bottom_button_calls.append((chat_id, message_text))
        return True

    async def forbidden_auto_reply(*args, **kwargs):
        raise AssertionError("matched bottom buttons should stop auto-reply processing")

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", fake_is_admin)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", _false)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", _false)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", _true)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", _false)
    monkeypatch.setattr(core_hooks, "_process_garage_features", _false)
    monkeypatch.setattr(core_hooks, "try_bottom_button_text_trigger", fake_bottom_button_trigger)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", forbidden_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
        effective_message=SimpleNamespace(text="排行榜", caption=None, message_id=10, sender_chat=None),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is True
    assert bottom_button_calls == [(-1001, "排行榜")]


@pytest.mark.asyncio
async def test_unified_group_handler_bottom_button_runs_before_garage_features(monkeypatch):
    session = _FakeSession()
    bottom_button_calls: list[tuple[int, str]] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        return _settings()

    async def fake_is_admin(context, chat_id: int, user_id: int):
        return False

    async def fake_bottom_button_trigger(update, context, chat_id: int, message_text: str):
        bottom_button_calls.append((chat_id, message_text))
        return True

    async def forbidden_garage(*args, **kwargs):
        raise AssertionError("matched bottom buttons should run before garage feature text handlers")

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", fake_is_admin)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", _false)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", _false)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", _true)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", _false)
    monkeypatch.setattr(core_hooks, "try_bottom_button_text_trigger", fake_bottom_button_trigger)
    monkeypatch.setattr(core_hooks, "_process_garage_features", forbidden_garage)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
        effective_message=SimpleNamespace(text="附近", caption=None, message_id=10, sender_chat=None),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is True
    assert bottom_button_calls == [(-1001, "附近")]


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
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", _false)
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
async def test_unified_group_handler_checks_banned_words_for_sender_chat(monkeypatch):
    session = _FakeSession()
    banned_word_calls: list[tuple[int, str]] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        return _settings()

    async def forbidden_user_check(*args, **kwargs):
        raise AssertionError("sender_chat messages must skip real-user checks")

    async def fake_banned_word(context, db, chat, user, message, message_text: str, settings):
        banned_word_calls.append((user.id, message_text))
        return True

    async def forbidden_auto_reply(*args, **kwargs):
        raise AssertionError("banned sender_chat messages should stop later auto-reply processing")

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", forbidden_user_check)
    monkeypatch.setattr(core_hooks, "_process_garage_features", _false)
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", fake_banned_word)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", forbidden_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=None,
        effective_message=SimpleNamespace(
            text="违禁词测试",
            caption=None,
            message_id=10,
            sender_chat=SimpleNamespace(id=-100777, title="Channel Identity", username="channel_identity"),
        ),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is True
    assert banned_word_calls == [(-100777, "违禁词测试")]


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


@pytest.mark.asyncio
async def test_unified_group_handler_checks_banned_words_in_media_caption(monkeypatch):
    session = _FakeSession()
    banned_word_calls: list[str] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        return _settings()

    async def fake_is_admin(context, chat_id: int, user_id: int):
        return False

    async def fake_banned_word(context, db, chat, user, message, message_text: str, settings):
        banned_word_calls.append(message_text)
        return True

    async def forbidden_auto_reply(*args, **kwargs):
        raise AssertionError("deleted banned-word captions should stop later auto-reply processing")

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", fake_is_admin)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", _false)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", _false)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", _true)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", _false)
    monkeypatch.setattr(core_hooks, "_process_garage_features", _false)
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", fake_banned_word)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", forbidden_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
        effective_message=SimpleNamespace(text=None, caption="视频里的违禁词", message_id=10, sender_chat=None),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is True
    assert banned_word_calls == ["视频里的违禁词"]


@pytest.mark.asyncio
async def test_unified_group_handler_continues_banned_word_check_after_force_subscribe_fail_open(monkeypatch):
    session = _FakeSession()
    events: list[str] = []

    async def fake_ensure(session, chat_id: int, **kwargs):
        return _settings()

    async def fake_is_admin(context, chat_id: int, user_id: int):
        return False

    async def fake_force_subscribe(context, chat, user, message, settings):
        events.append("force_subscribe_fail_open")
        return True

    async def fake_banned_word(context, db, chat, user, message, message_text: str, settings):
        events.append(f"banned_word:{message_text}")
        return True

    async def forbidden_auto_reply(*args, **kwargs):
        raise AssertionError("banned words must stop later auto-reply processing")

    monkeypatch.setattr(core_hooks.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(core_hooks, "is_user_admin", fake_is_admin)
    monkeypatch.setattr(core_hooks, "_process_rename_monitor", _false)
    monkeypatch.setattr(core_hooks, "_process_group_lock_controls", _false)
    monkeypatch.setattr(core_hooks, "_process_night_mode", _false)
    monkeypatch.setattr(core_hooks, "_process_alliance_joint_ban", _false)
    monkeypatch.setattr(core_hooks, "_check_force_subscribe", fake_force_subscribe)
    monkeypatch.setattr(core_hooks, "_process_new_member_limit", _false)
    monkeypatch.setattr(core_hooks, "_process_garage_features", _false)
    monkeypatch.setattr(core_hooks, "_process_banned_word_check", fake_banned_word)
    monkeypatch.setattr(core_hooks, "_process_auto_reply", forbidden_auto_reply)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
        effective_message=SimpleNamespace(text="违禁词测试", caption=None, message_id=10, sender_chat=None),
    )

    handled = await core_hooks.unified_group_message_handler(update, _context(session))

    assert handled is True
    assert events == ["force_subscribe_fail_open", "banned_word:违禁词测试"]


@pytest.mark.asyncio
async def test_banned_word_explicit_guard_falls_back_to_message_delete_when_executor_does_not_apply(monkeypatch):
    session = _FakeSession()
    settings = SimpleNamespace(anti_spam_rules={})
    set_rule_config(settings, "banned_words", {"enabled": True, "delete_message": True})

    class _User:
        id = 42
        username = "alice"
        first_name = "Alice"
        last_name = None
        language_code = "zh-CN"

        def mention_html(self):
            return "Alice"

    class _Message:
        message_id = 10
        deleted = False

        async def delete(self):
            self.deleted = True

    async def fake_match_banned_words(session, chat_id: int, message_text: str):
        return [SimpleNamespace(word="违禁词测试")]

    async def noop(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(*args, **kwargs):
        return SimpleNamespace(applied=False)

    monkeypatch.setattr(moderation_hooks, "match_banned_words", fake_match_banned_words)
    monkeypatch.setattr(moderation_hooks, "ensure_chat", noop)
    monkeypatch.setattr(moderation_hooks, "ensure_user", noop)
    monkeypatch.setattr(moderation_hooks, "apply_garbage_punishment", fake_apply_garbage_punishment)

    context = _context(session)
    context.bot = SimpleNamespace()
    db = context.application.bot_data["db"]
    message = _Message()

    handled = await moderation_hooks._process_banned_word_check(
        context,
        db,
        SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        _User(),
        message,
        "违禁词测试",
        settings,
    )

    assert handled is True
    assert message.deleted is True


@pytest.mark.asyncio
async def test_banned_word_explicit_guard_deletes_sender_chat_messages(monkeypatch):
    session = _FakeSession()
    settings = SimpleNamespace(anti_spam_rules={})
    set_rule_config(settings, "banned_words", {"enabled": True, "delete_message": True})
    applied_kwargs: list[dict[str, object]] = []

    class _SenderActor:
        id = -100777
        username = "channel_identity"
        first_name = "频道身份"
        last_name = None
        language_code = None

    class _Message:
        message_id = 10
        sender_chat = SimpleNamespace(id=-100777, title="频道身份", username="channel_identity")

    async def fake_match_banned_words(session, chat_id: int, message_text: str):
        return [SimpleNamespace(word="违禁词测试")]

    async def noop(*args, **kwargs):
        return None

    async def forbidden_ensure_user(*args, **kwargs):
        raise AssertionError("sender_chat banned-word checks must not persist a fake user")

    async def fake_apply_garbage_punishment(*args, **kwargs):
        applied_kwargs.append(kwargs)
        return SimpleNamespace(
            applied=True,
            delete_requested=True,
            delete_applied=True,
            escalation_requested=False,
            escalation_applied=False,
        )

    monkeypatch.setattr(moderation_hooks, "match_banned_words", fake_match_banned_words)
    monkeypatch.setattr(moderation_hooks, "ensure_chat", noop)
    monkeypatch.setattr(moderation_hooks, "ensure_user", forbidden_ensure_user)
    monkeypatch.setattr(moderation_hooks, "apply_garbage_punishment", fake_apply_garbage_punishment)

    context = _context(session)
    context.bot = SimpleNamespace()
    db = context.application.bot_data["db"]

    handled = await moderation_hooks._process_banned_word_check(
        context,
        db,
        SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        _SenderActor(),
        _Message(),
        "违禁词测试",
        settings,
    )

    assert handled is True
    assert applied_kwargs[0]["target_user_id"] == 0
    assert applied_kwargs[0]["target_label"] == "频道身份"
    assert applied_kwargs[0]["sender_chat_id"] == -100777


@pytest.mark.asyncio
async def test_banned_word_explicit_guard_notifies_when_all_actions_fail(monkeypatch):
    session = _FakeSession()
    settings = SimpleNamespace(anti_spam_rules={})
    set_rule_config(settings, "banned_words", {"enabled": True, "delete_message": True})
    sent_messages: list[tuple[int, str]] = []

    class _User:
        id = 42
        username = "alice"
        first_name = "Alice"
        last_name = None
        language_code = "zh-CN"

        def mention_html(self):
            return "Alice"

    class _Message:
        message_id = 10

        async def delete(self):
            raise RuntimeError("delete failed")

    class _Bot:
        async def send_message(self, chat_id: int, text: str, **kwargs):
            sent_messages.append((chat_id, text))

    async def fake_match_banned_words(session, chat_id: int, message_text: str):
        return [SimpleNamespace(word="违禁词测试")]

    async def noop(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(*args, **kwargs):
        return SimpleNamespace(applied=False)

    monkeypatch.setattr(moderation_hooks, "match_banned_words", fake_match_banned_words)
    monkeypatch.setattr(moderation_hooks, "ensure_chat", noop)
    monkeypatch.setattr(moderation_hooks, "ensure_user", noop)
    monkeypatch.setattr(moderation_hooks, "apply_garbage_punishment", fake_apply_garbage_punishment)

    context = _context(session)
    context.bot = _Bot()
    db = context.application.bot_data["db"]

    handled = await moderation_hooks._process_banned_word_check(
        context,
        db,
        SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        _User(),
        _Message(),
        "违禁词测试",
        settings,
    )

    assert handled is True
    assert sent_messages == [(-1001, "⚠️ 垃圾防护已命中，但处罚动作没有成功执行。\n请检查机器人是否仍是管理员，并拥有删除消息/禁言权限；也请重启机器人加载最新代码。")]


def test_group_business_handlers_run_verification_before_activity() -> None:
    names = [name for name, _handler in GroupMessageHandler()._get_business_handlers()]

    assert names.index("verification") < names.index("auction")
    assert names.index("verification") < names.index("game")
    assert names.index("verification") < names.index("lottery")
