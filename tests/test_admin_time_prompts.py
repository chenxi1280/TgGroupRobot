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

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, state_type: str, state_data: dict):
        started.append((state_type, state_data))

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
        CallbackParser.parse("adm:night:-1001:input:start"),
    )

    assert started and started[0][1]["field"] == "start"
    assert rendered and rendered[0][2] == "HTML"
    assert "最近整点示例" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"]


@pytest.mark.asyncio
async def test_group_lock_time_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, state_type: str, state_data: dict):
        started.append((state_type, state_data))

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
        CallbackParser.parse("adm:gl:-1001:input:open_time"),
    )

    assert started and started[0][1]["target_chat_id"] == -1001
    assert rendered and rendered[0][2] == "HTML"
    assert "点击下方蓝色按钮可直接复制" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"]


@pytest.mark.asyncio
async def test_game_auto_start_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, state_type: str, state_data: dict):
        started.append((state_type, state_data))

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
        CallbackParser.parse("gm:auto:-1001:start_time"),
    )

    assert started and started[0][0] == "game_wait_auto_start_time"
    assert rendered and rendered[0][2] == "HTML"
    assert "最近整点示例" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"]
