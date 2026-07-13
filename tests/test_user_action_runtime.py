from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.group_ops.group_hooks.control_new_member import _process_new_member_limit
from backend.features.group_ops.group_hooks.control_night import _process_night_mode
from backend.features.group_ops.group_hooks.control_lock import _process_group_lock_controls
from backend.features.group_ops.group_hooks import moderation as moderation_hooks
from backend.features.moderation.services.user_action_runtime import (
    delete_message_safely,
    execute_user_action,
    restrict_user_safely,
)


class _Bot:
    def __init__(
        self,
        *,
        delete_fails: bool = False,
        restrict_fails: bool = False,
        notify_fails: bool = False,
        set_permissions_fails: bool = False,
    ) -> None:
        self.delete_fails = delete_fails
        self.restrict_fails = restrict_fails
        self.notify_fails = notify_fails
        self.set_permissions_fails = set_permissions_fails
        self.deleted: list[tuple[int, int]] = []
        self.restricted: list[dict] = []
        self.messages: list[dict] = []
        self.banned: list[dict] = []
        self.permissions: list[dict] = []

    async def delete_message(self, *, chat_id, message_id):
        if self.delete_fails:
            raise RuntimeError("delete denied")
        self.deleted.append((chat_id, message_id))
        return True

    async def restrict_chat_member(self, **kwargs):
        if self.restrict_fails:
            raise RuntimeError("restrict denied")
        self.restricted.append(kwargs)
        return True

    async def ban_chat_member(self, **kwargs):
        if self.restrict_fails:
            raise RuntimeError("ban denied")
        self.banned.append(kwargs)
        return True

    async def send_message(self, chat_id, text, **kwargs):
        if self.notify_fails:
            raise RuntimeError("private blocked")
        self.messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return SimpleNamespace(message_id=900)

    async def get_chat_member(self, *, chat_id, user_id):
        return SimpleNamespace(status="administrator", can_promote_members=True)

    async def set_chat_permissions(self, *, chat_id, permissions):
        if self.set_permissions_fails:
            raise RuntimeError("set permissions denied")
        self.permissions.append({"chat_id": chat_id, "permissions": permissions})
        return True


class _Message:
    message_id = 11

    def __init__(self, *, delete_fails: bool = False) -> None:
        self.delete_fails = delete_fails
        self.fallback_deleted = False

    async def delete(self):
        if self.delete_fails:
            raise RuntimeError("fallback denied")
        self.fallback_deleted = True


def _context(bot: _Bot, *, bot_admin_ids: str = "7001"):
    settings = SimpleNamespace(bot_admin_ids=bot_admin_ids)
    return SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={"settings": settings}))


@pytest.mark.asyncio
async def test_delete_message_safely_uses_bot_delete_first() -> None:
    bot = _Bot()
    message = _Message()

    result = await delete_message_safely(
        _context(bot),
        chat_id=-1001,
        message=message,
        feature="测试功能",
        detail="删除测试",
    )

    assert result.delete_applied is True
    assert bot.deleted == [(-1001, 11)]
    assert message.fallback_deleted is False
    assert bot.messages == []


@pytest.mark.asyncio
async def test_delete_message_safely_falls_back_to_message_delete() -> None:
    bot = _Bot(delete_fails=True)
    message = _Message()

    result = await delete_message_safely(
        _context(bot),
        chat_id=-1001,
        message=message,
        feature="测试功能",
        detail="删除测试",
    )

    assert result.delete_applied is True
    assert message.fallback_deleted is True
    assert bot.messages == []


@pytest.mark.asyncio
async def test_delete_message_safely_notifies_admin_when_all_delete_attempts_fail() -> None:
    bot = _Bot(delete_fails=True)
    message = _Message(delete_fails=True)

    result = await delete_message_safely(
        _context(bot),
        chat_id=-1001,
        message=message,
        feature="测试功能",
        detail="删除测试",
    )

    assert result.delete_applied is False
    assert result.failed is True
    assert bot.messages[0]["chat_id"] == 7001
    assert "测试功能已命中" in bot.messages[0]["text"]
    assert "deleted=0" in bot.messages[0]["text"]
    assert "fallback denied" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_restrict_user_safely_notifies_admin_and_can_raise() -> None:
    bot = _Bot(restrict_fails=True)

    with pytest.raises(RuntimeError, match="restrict denied"):
        await restrict_user_safely(
            _context(bot),
            feature="测试禁言",
            chat_id=-1001,
            user_id=42,
            permissions=SimpleNamespace(can_send_messages=False),
            detail="禁言测试",
            raise_on_failure=True,
        )

    assert bot.messages[0]["chat_id"] == 7001
    assert "测试禁言已命中" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_execute_user_action_private_notify_failure_only_logs() -> None:
    bot = _Bot(delete_fails=True, restrict_fails=True, notify_fails=True)
    context = _context(bot)

    result = await execute_user_action(
        context,
        feature="测试处罚",
        chat_id=-1001,
        user_id=42,
        action="mute",
        detail="处罚测试",
        message=_Message(delete_fails=True),
        delete_message=True,
        mute_seconds=60,
    )

    assert result.failed is True
    assert bot.messages == []

    bot.notify_fails = False
    await execute_user_action(
        context,
        feature="测试处罚",
        chat_id=-1001,
        user_id=42,
        action="mute",
        detail="处罚测试",
        message=_Message(delete_fails=True),
        delete_message=True,
        mute_seconds=60,
    )
    assert bot.messages[0]["chat_id"] == 7001
    assert "测试处罚已命中" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_new_member_limit_delete_failure_still_blocks_and_notifies_admin() -> None:
    bot = _Bot(delete_fails=True)
    message = SimpleNamespace(
        message_id=21,
        text="https://example.com",
        caption=None,
        entities=[SimpleNamespace(type="url")],
        caption_entities=[],
        photo=None,
        video=None,
        document=None,
        animation=None,
        sticker=None,
        audio=None,
        voice=None,
        video_note=None,
    )

    async def fail_delete():
        raise RuntimeError("fallback denied")

    message.delete = fail_delete
    settings = SimpleNamespace(
        new_member_limit_enabled=True,
        new_member_limit_window_seconds=3600,
        new_member_limit_block_media=False,
        new_member_limit_block_links=True,
        new_member_limit_text_only=False,
        new_member_limit_delete_message=True,
        new_member_limit_warn_enabled=False,
    )

    async def joined_at_lookup(db, chat_id, user_id):
        import datetime as dt

        return dt.datetime.now(dt.UTC)

    blocked = await _process_new_member_limit(
        _context(bot),
        SimpleNamespace(),
        SimpleNamespace(id=-1001),
        user=SimpleNamespace(id=42, first_name="A", last_name=None, username=None),
        message=message,
        settings=settings,
        joined_at_lookup=joined_at_lookup,
    )

    assert blocked is True
    assert bot.messages[0]["chat_id"] == 7001
    assert "新人限制已命中" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_night_mode_delete_failure_still_blocks_and_notifies_admin() -> None:
    bot = _Bot(delete_fails=True)
    message = _Message(delete_fails=True)
    settings = SimpleNamespace(
        night_mode_enabled=True,
        night_mode_exempt_admin=True,
        night_mode_whitelist_user_ids=[],
        night_mode_delete_message=True,
        night_mode_warn_enabled=False,
    )

    blocked = await _process_night_mode(
        _context(bot),
        SimpleNamespace(id=-1001),
        SimpleNamespace(id=42),
        message=message,
        settings=settings,
        is_admin=False,
        night_time_check=lambda _: True,
    )

    assert blocked is True
    assert bot.messages[0]["chat_id"] == 7001
    assert "夜间管控已命中" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_alliance_joint_ban_failure_still_stops_later_processing(monkeypatch) -> None:
    bot = _Bot(restrict_fails=True)
    hit = (SimpleNamespace(), SimpleNamespace(source_operator_user_id=99))

    async def fake_get_joint_ban_hit(session, *, chat_id, target_user_id):
        return hit

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    class _Db:
        def session_factory(self):
            return _Session()

    monkeypatch.setattr(moderation_hooks.AllianceService, "get_joint_ban_hit", fake_get_joint_ban_hit)

    handled = await moderation_hooks._process_alliance_joint_ban(
        _context(bot),
        _Db(),
        SimpleNamespace(id=-1001),
        user=SimpleNamespace(id=42),
        message=SimpleNamespace(message_id=31, sender_chat=None),
    )

    assert handled is True
    assert bot.messages[0]["chat_id"] == 7001
    assert "联盟封禁已命中" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_group_lock_phrase_delete_runs_only_after_permission_success() -> None:
    bot = _Bot(set_permissions_fails=True)
    message = _Message()
    settings = SimpleNamespace(
        group_lock_schedule_enabled=False,
        group_lock_phrase_enabled=True,
        group_lock_open_phrase="开群",
        group_lock_close_phrase="关群",
        group_lock_delete_notice_mode="delete",
    )

    handled = await _process_group_lock_controls(
        _context(bot),
        SimpleNamespace(id=-1001),
        SimpleNamespace(id=42),
        message=message,
        settings=settings,
        is_admin=True,
        message_text="关群",
    )

    assert handled is True
    assert message.fallback_deleted is False
    assert bot.messages[0]["chat_id"] == 7001
    assert "夜间管控已命中" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_legacy_banned_word_uses_unified_action_diagnostic(monkeypatch) -> None:
    bot = _Bot(delete_fails=True, restrict_fails=True)
    word = SimpleNamespace(word="违禁词测试", action="mute", notify=False, mute_duration=60)

    async def fake_match_banned_words(session, chat_id, message_text):
        return [word]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    class _Db:
        def session_factory(self):
            return _Session()

    monkeypatch.setattr(moderation_hooks, "match_banned_words", fake_match_banned_words)

    handled = await moderation_hooks._process_banned_word_check(
        _context(bot),
        _Db(),
        SimpleNamespace(id=-1001),
        user=SimpleNamespace(id=42, username=None),
        message=_Message(delete_fails=True),
        message_text="违禁词测试",
        settings=None,
    )

    assert handled is True
    assert any(message["chat_id"] == 7001 and "违禁词已命中" in message["text"] for message in bot.messages)
