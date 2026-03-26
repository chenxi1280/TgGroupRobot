from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers.dispatcher.group_message_handler import GroupMessageHandler
from bot.handlers.group_message_handler import _process_group_lock_controls
from bot.keyboards.admin.auto_delete import auto_delete_config_keyboard
from bot.services.welcome_service import WelcomeService


@pytest.mark.asyncio
async def test_group_dispatcher_short_circuits_business_handlers_when_core_stops():
    dispatcher = GroupMessageHandler()
    calls: list[str] = []

    async def fake_core(update, context):
        calls.append("core")
        return True

    async def fake_business(update, context):
        calls.append("business")
        return None

    dispatcher._core_handler = fake_core
    dispatcher._business_handlers = [("business", fake_business)]

    update = SimpleNamespace()
    context = SimpleNamespace()
    chat = SimpleNamespace(id=-1001)
    user = SimpleNamespace(id=42)

    await dispatcher.handle(update, context, chat, user, "hello")

    assert calls == ["core"]


@pytest.mark.asyncio
async def test_group_lock_schedule_disabled_does_not_apply_permissions():
    calls: list[bool] = []

    async def fake_set_chat_permissions(*, chat_id, permissions):
        calls.append(permissions.can_send_messages)

    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={}),
        bot=SimpleNamespace(set_chat_permissions=fake_set_chat_permissions),
    )
    chat = SimpleNamespace(id=-1001)
    user = SimpleNamespace(id=42)
    message = SimpleNamespace(delete=lambda: None)
    settings = SimpleNamespace(
        group_lock_schedule_enabled=False,
        group_lock_open_time=None,
        group_lock_close_time=None,
        group_lock_phrase_enabled=False,
    )

    handled = await _process_group_lock_controls(context, chat, user, message, settings, False, "hello")

    assert handled is False
    assert calls == []


@pytest.mark.asyncio
async def test_group_lock_phrase_requires_promote_members():
    calls: list[bool] = []

    async def fake_set_chat_permissions(*, chat_id, permissions):
        calls.append(permissions.can_send_messages)

    async def fake_get_chat_member(*, chat_id, user_id):
        return SimpleNamespace(status="administrator", can_promote_members=False)

    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={}),
        bot=SimpleNamespace(
            set_chat_permissions=fake_set_chat_permissions,
            get_chat_member=fake_get_chat_member,
        ),
    )
    chat = SimpleNamespace(id=-1001)
    user = SimpleNamespace(id=42)
    message = SimpleNamespace(delete=lambda: None)
    settings = SimpleNamespace(
        group_lock_schedule_enabled=False,
        group_lock_open_time=None,
        group_lock_close_time=None,
        group_lock_phrase_enabled=True,
        group_lock_open_phrase="开群了",
        group_lock_close_phrase="关群了",
    )

    handled = await _process_group_lock_controls(context, chat, user, message, settings, True, "关群了")

    assert handled is False
    assert calls == []


def test_auto_delete_keyboard_keeps_anonymous_toggle():
    settings = SimpleNamespace(
        auto_delete_join=False,
        auto_delete_left=False,
        auto_delete_pinned=False,
        auto_delete_avatar=False,
        auto_delete_title=False,
        auto_delete_anonymous=True,
    )

    keyboard = auto_delete_config_keyboard(settings, -100123)
    anonymous_row = keyboard.inline_keyboard[5]

    assert anonymous_row[0].text == "匿名消息："
    assert anonymous_row[0].callback_data == "autodel:noop:anonymous:-100123"
    assert anonymous_row[1].callback_data == "autodel:set:anonymous:1:-100123"
    assert anonymous_row[2].callback_data == "autodel:set:anonymous:0:-100123"


@pytest.mark.asyncio
async def test_welcome_service_update_field_can_clear_cover(monkeypatch):
    welcome = SimpleNamespace(
        title="待配置",
        enabled=True,
        welcome_mode="after_verify",
        cover_media_type="photo",
        cover_media_file_id="file123",
        text_content="hello",
        buttons=[],
        delete_mode="delay",
        delete_delay_seconds=15,
        last_sent_message_id=None,
    )

    async def fake_get_message(session, chat_id, welcome_id):
        return welcome

    monkeypatch.setattr(WelcomeService, "get_message", fake_get_message)

    class _Session:
        async def flush(self):
            return None

    await WelcomeService.update_field(
        _Session(),
        -1001,
        1,
        cover_media_type=None,
        cover_media_file_id=None,
    )

    assert welcome.cover_media_type is None
    assert welcome.cover_media_file_id is None
