from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.shared.callback_parser import CallbackParser


class _FakeSession:
    async def commit(self):
        return None


class _FakeSessionContext:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def session_factory(self):
        return _FakeSessionContext()


@pytest.mark.asyncio
async def test_night_mode_time_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, *, state_type: str, payload: dict):
        started.append((state_type, payload))

    async def fake_safe_edit(update, text: str, reply_markup=None, parse_mode=None):
        rendered.append((text, reply_markup, parse_mode))

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._handle_night_mode(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("adm:night:-1001:input:start"),
    )

    assert started and started[0][1]["field"] == "start"
    assert rendered and rendered[0][2] == "HTML"
    assert "最近整点示例" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"]


@pytest.mark.asyncio
async def test_group_lock_time_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, *, state_type: str, payload: dict):
        started.append((state_type, payload))

    async def fake_safe_edit(update, text: str, reply_markup=None, parse_mode=None):
        rendered.append((text, reply_markup, parse_mode))

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._handle_group_lock(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("adm:gl:-1001:input:open_time"),
    )

    assert started and started[0][1]["target_chat_id"] == -1001
    assert rendered and rendered[0][2] == "HTML"
    assert "点击下方蓝色按钮可直接复制" in rendered[0][0]
    assert "夜间管控" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"]


@pytest.mark.asyncio
async def test_night_control_start_input_syncs_legacy_group_lock_time(monkeypatch):
    from backend.features.admin.module_settings import limit_night_command_inputs

    settings = SimpleNamespace(
        night_mode_start_time=None,
        night_mode_end_time=None,
        group_lock_close_time=None,
        group_lock_open_time=None,
    )
    state = SimpleNamespace(chat_id=-1001, state_data={"target_chat_id": -1001, "field": "start"})
    shown: list[int] = []

    async def fake_require_settings_manage(update, context, target_chat_id):
        return True

    async def fake_get_chat_settings(session, target_chat_id):
        return settings

    async def fake_clear_state(session, *, target_chat_id, user_id):
        return None

    async def fake_show_menu(update, context, target_chat_id):
        shown.append(target_chat_id)

    session = _FakeSession()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=lambda text: None),
    )
    context = SimpleNamespace()

    monkeypatch.setattr(limit_night_command_inputs, "require_settings_manage", fake_require_settings_manage)
    monkeypatch.setattr(limit_night_command_inputs.admin_module(), "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(limit_night_command_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(limit_night_command_inputs.admin_handler_instance(), "_show_night_mode_menu", fake_show_menu)

    await limit_night_command_inputs.handle_night_mode_input(update, context, session, state=state, message_text="23:30")

    assert settings.night_mode_start_time == "23:30"
    assert settings.group_lock_close_time == "23:30"
    assert shown == [-1001]


@pytest.mark.asyncio
async def test_game_auto_start_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, *, state_type: str, payload: dict):
        started.append((state_type, payload))

    async def fake_safe_edit(update, text: str, reply_markup=None, parse_mode=None):
        rendered.append((text, reply_markup, parse_mode))

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._handle_game(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("gm:auto:-1001:start_time"),
    )

    assert started and started[0][0] == "game_wait_auto_start_time"
    assert rendered and rendered[0][2] == "HTML"
    assert "最近整点示例" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"]
