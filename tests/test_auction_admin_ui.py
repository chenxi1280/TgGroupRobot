from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.activity import bottom_button as bottom_button_admin
from backend.platform.db.schema.models.expansion import BottomButtonLayout
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
async def test_show_auction_menu_contains_activity_list_button(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_set_current_chat(*args, **kwargs):
        return None

    async def fake_get_chat_title(db, chat_id: int):
        return "测试群"

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(
            enabled=True,
            pin_message_enabled=False,
            auto_extend_enabled=True,
            create_permission="admin",
            points_mode="none",
        )

    async def fake_list_recent(session, chat_id: int, limit: int = 5):
        return []

    async def fake_safe_edit(update, *, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler._admin_handler, "_get_chat_title", fake_get_chat_title)
    monkeypatch.setattr(admin_handler, "get_auction_setting", fake_get_setting)
    monkeypatch.setattr(admin_handler, "list_recent_auctions", fake_list_recent)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_auction_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in captured["keyboard"]]
    assert ["📋 活动列表"] in rows
    assert all("仅管理员" not in button for row in rows for button in row)


@pytest.mark.asyncio
async def test_show_auction_list_uses_one_page_when_empty(monkeypatch):
    rendered: list[str] = []

    async def fake_list_auctions(session, chat_id: int, *, page: int = 0, page_size: int = 10):
        return [], 0

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler, "list_auctions", fake_list_auctions)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_auction_list(update, context, -1001, page=0)

    assert rendered
    assert "0 条数据，第 1 页/共 1 页" in rendered[0]


@pytest.mark.asyncio
async def test_bottom_button_layout_menu_renders_position_controls(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_list_layouts(session, chat_id: int):
        return [
            BottomButtonLayout(
                id=1,
                chat_id=chat_id,
                row_no=1,
                col_no=1,
                button_text="报销加分必看",
                payload_text="报销加分必看",
                action_mode="send",
                sort_key=11,
            ),
            BottomButtonLayout(
                id=2,
                chat_id=chat_id,
                row_no=1,
                col_no=2,
                button_text="精品榜榜单",
                payload_text="精品榜榜单",
                action_mode="send",
                sort_key=12,
            ),
            BottomButtonLayout(
                id=3,
                chat_id=chat_id,
                row_no=2,
                col_no=2,
                button_text="按钮",
                payload_text="按钮",
                action_mode="send",
                sort_key=22,
            ),
        ]

    async def fake_safe_edit(update, *, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(bottom_button_admin, "list_bottom_button_layouts", fake_list_layouts)
    monkeypatch.setattr(bottom_button_admin, "build_management_layout_preview", lambda layouts: "预览")
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_bottom_button_layout_menu(update, context, -1001)

    text = captured["text"]
    rows = [[button.text for button in row] for row in captured["keyboard"]]
    callbacks = [[button.callback_data for button in row] for row in captured["keyboard"]]

    assert "⌨️ 底部按钮｜按钮设置" in text
    assert "每行最多4个按钮" in text
    assert rows[0] == ["报销加分必看", "精品榜榜单", "➕ 按钮"]
    assert callbacks[0][2] == "btm:layout:-1001:add:1:3"
    assert rows[1] == ["⚠️ 空", "按钮", "➕ 按钮"]
    assert callbacks[1][0] == "btm:layout:-1001:add:2:1"
    assert callbacks[1][2] == "btm:layout:-1001:add:2:3"
    assert rows[2] == ["➕ 按钮"]
    assert callbacks[2][0] == "btm:layout:-1001:add:3:1"
    assert rows[-1] == ["♻️ 清空按钮", "🔙 返回"]
    assert callbacks[-1][1] == "btm:home:-1001"


@pytest.mark.asyncio
async def test_unimplemented_feature_redirects_auction_todo_to_real_menu(monkeypatch):
    called: dict[str, int] = {}

    async def fake_show_auction_menu(update, context, chat_id: int):
        called["chat_id"] = chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "_show_auction_menu", fake_show_auction_menu)

    update = SimpleNamespace()
    context = SimpleNamespace()
    callback_data = CallbackParser.parse("adm:todo:-1009900:auction")

    await admin_handler._admin_handler._show_unimplemented_feature(update, context, -1009900, callback_data)

    assert called == {"chat_id": -1009900}
