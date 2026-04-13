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
        ["状态：", "✅ 启用", "关闭"],
        ["模式：", "✅ 验证后欢迎", "进群欢迎"],
        ["标题备注", "修改封面"],
        ["修改文本", "修改按钮"],
        ["🏖️ 预览效果", "⏱️ 延迟删除"],
        ["❌ 删除配置", "🔙 返回"],
    ]
