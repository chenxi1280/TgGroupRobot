from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.group_ops.group_hooks.control_force_subscribe import (
    _check_force_subscribe,
    diagnose_force_subscribe_targets,
)


class _Bot:
    def __init__(self, statuses: dict[object, str], chat_titles: dict[object, str] | None = None) -> None:
        self.statuses = statuses
        self.chat_titles = chat_titles or {}
        self.get_chat_calls: list[object] = []
        self.get_chat_member_calls: list[tuple[object, int]] = []
        self.messages: list[dict] = []
        self.restrict_calls: list[dict] = []

    async def get_chat(self, *, chat_id):
        self.get_chat_calls.append(chat_id)
        username = str(chat_id).lstrip("@") if isinstance(chat_id, str) and chat_id.startswith("@") else None
        return SimpleNamespace(type="channel", title=self.chat_titles[chat_id], username=username)

    async def get_chat_member(self, *, chat_id, user_id):
        self.get_chat_member_calls.append((chat_id, user_id))
        status = self.statuses[chat_id]
        if isinstance(status, Exception):
            raise status
        if isinstance(status, dict):
            return SimpleNamespace(**status)
        return SimpleNamespace(status=status)

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return SimpleNamespace(message_id=99)

    async def restrict_chat_member(self, chat_id, user_id, **kwargs):
        self.restrict_calls.append({"chat_id": chat_id, "user_id": user_id, **kwargs})
        return True


class _Message:
    message_id = 12

    def __init__(self) -> None:
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


def _settings(**overrides):
    data = {
        "force_subscribe_enabled": True,
        "force_subscribe_bound_channel_1": "@channel_a",
        "force_subscribe_bound_channel_2": None,
        "force_subscribe_check_mode": "all",
        "force_subscribe_not_subscribed_action": "delete_only",
        "force_subscribe_guide_text": "{member}，请关注后发言。",
        "force_subscribe_delete_warn_after_seconds": 0,
        "force_subscribe_cover_media_type": None,
        "force_subscribe_cover_file_id": None,
        "force_subscribe_custom_buttons_enabled": False,
        "force_subscribe_buttons": [],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _context(bot: _Bot):
    return SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={}))


def _chat():
    return SimpleNamespace(id=-100123)


def _user():
    return SimpleNamespace(id=42, first_name="Alice", last_name=None, username=None)


@pytest.mark.asyncio
async def test_force_subscribe_normalizes_username_and_t_me_targets() -> None:
    bot = _Bot({"@channel_a": "member", "@channel_b": "administrator"})
    message = _Message()

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        message,
        _settings(force_subscribe_bound_channel_2="https://t.me/channel_b"),
    )

    assert allowed is True
    assert message.deleted is False
    assert bot.get_chat_member_calls == [("@channel_a", 42), ("@channel_b", 42)]


@pytest.mark.asyncio
async def test_force_subscribe_rejects_legacy_numeric_target_without_blocking_member() -> None:
    bot = _Bot({})
    message = _Message()

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        message,
        _settings(force_subscribe_bound_channel_1="-100456"),
    )

    assert allowed is True
    assert message.deleted is False
    assert bot.get_chat_member_calls == []
    assert bot.messages[0]["chat_id"] == -100123
    assert "强制订阅配置异常" in bot.messages[0]["text"]
    assert "已临时跳过强制订阅校验" in bot.messages[0]["text"]
    assert "普通成员仍会继续进入违禁词/垃圾防护检测" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_force_subscribe_any_mode_allows_one_matching_target() -> None:
    bot = _Bot({"@channel_a": "left", "@channel_b": "member"})
    message = _Message()

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        message,
        _settings(
            force_subscribe_bound_channel_2="http://t.me/channel_b",
            force_subscribe_check_mode="any",
        ),
    )

    assert allowed is True
    assert message.deleted is False
    assert bot.get_chat_member_calls == [("@channel_a", 42), ("@channel_b", 42)]


@pytest.mark.asyncio
async def test_force_subscribe_deletes_and_warns_unsubscribed_member() -> None:
    bot = _Bot({"@channel_a": "left"}, chat_titles={"@channel_a": "频道 A"})
    message = _Message()

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        message,
        _settings(force_subscribe_not_subscribed_action="delete_and_warn"),
    )

    assert allowed is False
    assert message.deleted is True
    assert bot.messages[0]["chat_id"] == -100123
    assert bot.messages[0]["text"] == "Alice，请关注后发言。"
    assert bot.messages[0]["reply_markup"].inline_keyboard[0][0].text == "频道 A"
    assert bot.messages[0]["reply_markup"].inline_keyboard[0][0].url == "https://t.me/channel_a"


@pytest.mark.asyncio
async def test_force_subscribe_mutes_and_warns_unsubscribed_member() -> None:
    bot = _Bot({"@channel_a": "kicked"})

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        _Message(),
        _settings(force_subscribe_not_subscribed_action="mute"),
    )

    assert allowed is False
    assert bot.restrict_calls[0]["chat_id"] == -100123
    assert bot.restrict_calls[0]["user_id"] == 42
    assert bot.restrict_calls[0]["permissions"].can_send_messages is False
    assert bot.messages[0]["text"] == "Alice，请关注后发言。"


@pytest.mark.asyncio
async def test_force_subscribe_all_mode_skips_inaccessible_target_when_valid_target_is_subscribed() -> None:
    bot = _Bot({"@channel_a": "member", "@channel_b": RuntimeError("chat not found")})
    message = _Message()

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        message,
        _settings(
            force_subscribe_bound_channel_2="@channel_b",
            force_subscribe_check_mode="all",
            force_subscribe_not_subscribed_action="delete_only",
        ),
    )

    assert allowed is True
    assert message.deleted is False
    assert bot.get_chat_member_calls == [("@channel_a", 42), ("@channel_b", 42)]
    assert "部分目标配置异常" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_force_subscribe_bare_username_is_config_issue_and_does_not_block() -> None:
    bot = _Bot({})
    message = _Message()

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        message,
        _settings(force_subscribe_bound_channel_1="TgMgtPrd_bot"),
    )

    assert allowed is True
    assert message.deleted is False
    assert bot.get_chat_member_calls == []
    assert "强制订阅配置异常" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_force_subscribe_valid_target_still_blocks_unsubscribed_member() -> None:
    bot = _Bot({"@channel_a": "left"})
    message = _Message()

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        message,
        _settings(force_subscribe_not_subscribed_action="delete_only"),
    )

    assert allowed is False
    assert message.deleted is True
    assert bot.messages == []


@pytest.mark.asyncio
async def test_force_subscribe_restricted_member_with_is_member_true_is_allowed() -> None:
    bot = _Bot({"@channel_a": {"status": "restricted", "is_member": True}})

    allowed = await _check_force_subscribe(
        _context(bot),
        _chat(),
        _user(),
        _Message(),
        _settings(),
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_force_subscribe_target_diagnostics_surface_invalid_and_permission_issues() -> None:
    bot = _Bot(
        {
            "@channel_a": {"status": "member"},
            "@channel_b": {"status": "member"},
        },
        chat_titles={"@channel_a": "频道 A", "@channel_b": "频道 B"},
    )
    bot.id = 999

    diagnostics = await diagnose_force_subscribe_targets(
        _context(bot),
        _settings(
            force_subscribe_bound_channel_1="https://t.me/+invite",
            force_subscribe_bound_channel_2="@channel_b",
        ),
    )

    assert diagnostics == [
        "绑定目标1格式无效，请重新绑定公开频道/群组的 @用户名。",
        "绑定目标2机器人不是管理员，可能无法稳定校验订阅。",
    ]
