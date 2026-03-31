from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import admin_handler


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
async def test_verification_menu_uses_four_entry_home(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_set_current_chat(*args, **kwargs):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            verification_enabled=True,
            verification_mode="math",
            join_spam_guard_enabled=False,
            join_self_review_enabled=True,
            join_burst_enabled=False,
        )

    async def fake_get_chat_title(db, chat_id: int):
        return "测试群"

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_get_chat_title", fake_get_chat_title)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_verification_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert rows == [
        ["🛡️ 进群验证"],
        ["🚯 垃圾拦截"],
        ["📝 进群自助审核"],
        ["🚪 禁止批量进群"],
        ["🔙 返回"],
    ]
    assert "进群验证：✅ 开启｜当前方式：数学题" in rendered["text"]
    assert "进群自助审核：✅ 开启" in rendered["text"]


@pytest.mark.asyncio
async def test_verification_spam_guard_page_shows_live_controls(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            join_spam_guard_enabled=True,
            join_spam_detect_rules_count=3,
            join_spam_send_invalid_msg_enabled=False,
            join_spam_mute_member_enabled=True,
            join_spam_kick_member_enabled=False,
            join_spam_tip_delete_after_seconds=120,
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    class _FakeDb:
        def session_factory(self):
            return _FakeSessionContext(_FakeSession())

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._show_join_spam_guard_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert rows == [
        ["✅ 状态", "🧪 阈值 3"],
        ["💬 提示 ❌", "🔇 禁言 ✅"],
        ["👢 踢出 ❌", "⏱️ 删除 120s"],
        ["🔙 返回"],
    ]
    assert "📌 状态：✅ 开启" in rendered["text"]
