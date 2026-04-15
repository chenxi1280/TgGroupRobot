from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.verification.welcome_service import WelcomeService


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

    await admin_handler._admin_handler._show_welcome_detail_menu(update, context, -1001, 9)

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

    await admin_handler._admin_handler._show_welcome_detail_menu(update, context, -1001, 9)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert "📮 标题备注: 【等待设置】" in rendered["text"]
    assert rows[2][0] == "标题备注"
