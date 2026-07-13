from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.welcome.controller import format_welcome_text_input_prompt
from backend.features.verification.welcome_service import WelcomeService
from backend.shared.callback_parser import CallbackParser


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, session):
        self._session = session

    def session_factory(self):
        return _FakeSessionContext(self._session)


@pytest.mark.asyncio
async def test_welcome_detail_keyboard_matches_doc_style(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_message(session, chat_id: int, welcome_id: int):
        return SimpleNamespace(
            id=welcome_id,
            title="欢迎词 1",
            enabled=True,
            welcome_mode="after_verify",
            cover_media_file_id=None,
            text_content="你好 {member}",
            buttons=[],
            delete_mode="seconds",
            delete_delay_seconds=60,
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(WelcomeService, "get_message", fake_get_message)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_welcome_detail_menu(update, context, -1001, welcome_id=9)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert rows == [
        ["⚙️ 状态:", "✅ 启用", "关闭"],
        ["🪩 模式:", "✅ 验证后欢迎", "进群欢迎"],
        ["✅ 标题备注", "设置封面"],
        ["✅ 设置文本", "设置按钮"],
        ["🏖️ 预览效果", "✅ 🕘 延迟删除"],
        ["❌ 删除配置", "🔙 返回"],
    ]
    assert rendered["keyboard"][3][1].callback_data == "btned:open:welcome:-1001:9"
    assert "📮 标题备注: 欢迎词 1" in rendered["text"]
    assert "🏞️ 封面设置: 【等待设置】" in rendered["text"]
    assert "📄 文本内容: 你好 {member}" in rendered["text"]
    assert "⚙️ 状态: ✅ 启用" in rendered["text"]


@pytest.mark.asyncio
async def test_welcome_default_title_is_not_marked_configured(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_message(session, chat_id: int, welcome_id: int):
        return SimpleNamespace(
            id=welcome_id,
            title="待配置",
            enabled=False,
            welcome_mode="after_verify",
            cover_media_file_id=None,
            cover_media_type=None,
            text_content="你好 {member}",
            buttons=[],
            delete_mode="seconds",
            delete_delay_seconds=15,
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(WelcomeService, "get_message", fake_get_message)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_welcome_detail_menu(update, context, -1001, welcome_id=9)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert "📮 标题备注: 【等待设置】" in rendered["text"]
    assert rows[2][0] == "标题备注"


@pytest.mark.asyncio
async def test_welcome_text_input_prompt_shows_current_text_and_tokens(monkeypatch):
    rendered: dict[str, object] = {}
    started: dict[str, object] = {}

    async def fake_get_message(session, chat_id: int, welcome_id: int):
        return SimpleNamespace(text_content="{member}，欢迎加入{group}。")

    async def fake_start_text_input_state(context, user_id, state_chat_id, state_type, payload):
        started["user_id"] = user_id
        started["state_chat_id"] = state_chat_id
        started["state_type"] = state_type
        started["payload"] = payload

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(WelcomeService, "get_message", fake_get_message)
    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._handle_welcome(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("adm:wel:-1001:input:9:text"),
    )

    assert started == {
        "user_id": 42,
        "state_chat_id": -1001,
        "state_type": "welcome_text_input",
        "payload": {"target_chat_id": -1001, "welcome_id": 9},
    }
    assert rendered["text"] == format_welcome_text_input_prompt("{member}，欢迎加入{group}。")
    assert [[button.text for button in row] for row in rendered["keyboard"]] == [["🔙 返回"]]
