from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.admin_handler import handle_force_subscribe_channel_input
from backend.shared.callback_parser import CallbackParser


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def flush(self):
        return None


class _Db:
    def __init__(self):
        self.session_factory = lambda: _Session()


@pytest.mark.asyncio
async def test_force_subscribe_menu_shows_action_row(monkeypatch):
    rendered: list[tuple[str, object]] = []
    settings = SimpleNamespace(
        force_subscribe_enabled=True,
        force_subscribe_bound_channel_1="@channel_a",
        force_subscribe_bound_channel_2=None,
        force_subscribe_delete_warn_after_seconds=60,
        force_subscribe_guide_text="请先订阅",
        force_subscribe_cover_file_id=None,
        force_subscribe_custom_buttons_enabled=False,
        force_subscribe_buttons=[],
        force_subscribe_not_subscribed_action="warn_only",
        force_subscribe_check_mode="all",
    )

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_force_subscribe_menu(update, context, -100123)

    assert rendered
    text, keyboard = rendered[0]
    assert "没订阅时处理: 仅提示订阅" in text
    assert "订阅判定: ✅ 全部频道都订阅" in text
    assert keyboard.inline_keyboard[0][0].text == "⚙️ 状态："
    assert keyboard.inline_keyboard[0][1].text == "✅ 启动"
    assert keyboard.inline_keyboard[5][0].text == "⚙️ 订阅判定："
    assert keyboard.inline_keyboard[6][0].text == "⚙️ 没订阅时处理："
    assert keyboard.inline_keyboard[6][1].text == "仅提示订阅"


@pytest.mark.asyncio
async def test_force_subscribe_cycle_action_updates_setting(monkeypatch):
    settings = SimpleNamespace(
        force_subscribe_not_subscribed_action="delete_and_warn",
        force_subscribe_check_mode="all",
    )
    shown: list[int] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_show(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:cycle_action"),
    )

    assert settings.force_subscribe_not_subscribed_action == "delete_only"
    assert shown == [-100123]


@pytest.mark.asyncio
async def test_force_subscribe_cycle_check_mode_updates_setting(monkeypatch):
    settings = SimpleNamespace(force_subscribe_check_mode="all")
    shown: list[int] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_show(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:cycle_check_mode"),
    )

    assert settings.force_subscribe_check_mode == "any"
    assert shown == [-100123]


@pytest.mark.asyncio
async def test_force_subscribe_preview_uses_channel_buttons(monkeypatch):
    rendered: list[tuple[str, object]] = []
    settings = SimpleNamespace(
        force_subscribe_custom_buttons_enabled=False,
        force_subscribe_buttons=[],
        force_subscribe_bound_channel_1="@channel_a",
        force_subscribe_bound_channel_2="https://t.me/channel_b",
    )

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:preview"),
    )

    assert rendered
    text, keyboard = rendered[0]
    assert "预览效果" in text
    assert keyboard.inline_keyboard[0][0].text == "@channel_a"
    assert keyboard.inline_keyboard[1][0].text == "https://t.me/channel_b"
    assert keyboard.inline_keyboard[-1][0].callback_data == "adm:menu:forcesub:-100123"


@pytest.mark.asyncio
async def test_force_subscribe_buttons_input_accepts_line_format(monkeypatch):
    settings = SimpleNamespace(
        force_subscribe_buttons=[],
        force_subscribe_custom_buttons_enabled=False,
    )
    shown: list[int] = []
    clear_calls: list[tuple[int, int]] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_clear_user_state(session, *, chat_id: int, user_id: int):
        clear_calls.append((chat_id, user_id))

    async def fake_show_force_subscribe_menu(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    from backend.platform.state import state_service
    monkeypatch.setattr(state_service, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show_force_subscribe_menu)

    async def _reply_text(*args, **kwargs):
        return None

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=9),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))
    session = _Session()
    state = SimpleNamespace(
        state_type="force_subscribe_buttons_input",
        state_data={"target_chat_id": -100123},
        chat_id=9,
    )

    await handle_force_subscribe_channel_input(
        update,
        context,
        session,
        state,
        "加入频道|https://t.me/channel_a\n联系客服|https://t.me/channel_b",
    )

    assert settings.force_subscribe_custom_buttons_enabled is True
    assert settings.force_subscribe_buttons == [
        [{"text": "加入频道", "url": "https://t.me/channel_a"}],
        [{"text": "联系客服", "url": "https://t.me/channel_b"}],
    ]
    assert shown == [-100123]
    assert clear_calls == [(-100123, 9), (9, 9)]
