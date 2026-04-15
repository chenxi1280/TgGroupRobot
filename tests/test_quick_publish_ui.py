from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler


class _Session:
    async def commit(self):
        return None


class _SessionContext:
    async def __aenter__(self):
        return _Session()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Db:
    def session_factory(self):
        return _SessionContext()


@pytest.mark.asyncio
async def test_quick_publish_menu_uses_shared_message_panel(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_title(db, chat_id: int):
        return "测试群"

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler._admin_handler, "_get_chat_title", fake_get_chat_title)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": _Db()}),
        user_data={
            "quick_publish_draft": {
                str(-1001): {
                    "text": "hello world",
                    "media_type": "photo",
                    "media_file_id": "photo-file-id",
                    "buttons": [[{"text": "官网", "url": "https://example.com"}]],
                }
            }
        },
    )

    await admin_handler._admin_handler._show_quick_publish_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert "🎯 目标群组: 测试群" in rendered["text"]
    assert "🏞️ 媒体内容: 已设置 photo" in rendered["text"]
    assert "📄 文本内容: hello world" in rendered["text"]
    assert "⭕ 设置按钮: 已设置 1 个" in rendered["text"]
    assert "🚀 可发送: 已就绪" in rendered["text"]
    assert rows[0] == ["✅ 设置文本", "✅ 设置媒体"]
    assert rows[1] == ["✅ 设置按钮", "🧹 清空草稿"]
