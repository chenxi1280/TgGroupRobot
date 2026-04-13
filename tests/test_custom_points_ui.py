from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.ui.points_extended import custom_point_detail_keyboard


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


def test_custom_point_detail_keyboard_marks_current_status():
    enabled_item = SimpleNamespace(id=7, enabled=True, name="诚心分", rank_command="诚心榜")
    disabled_item = SimpleNamespace(id=8, enabled=False, name="贡献值", rank_command=None)

    enabled_rows = [[button.text for button in row] for row in custom_point_detail_keyboard(enabled_item, -1001).inline_keyboard]
    disabled_rows = [[button.text for button in row] for row in custom_point_detail_keyboard(disabled_item, -1001).inline_keyboard]

    assert enabled_rows[0] == ["⚙️ 状态：", "✅ 启动", "关闭"]
    assert disabled_rows[0] == ["⚙️ 状态：", "启动", "❌ 关闭"]


@pytest.mark.asyncio
async def test_show_custom_points_menu_uses_one_page_when_empty(monkeypatch):
    rendered: list[str] = []

    async def fake_set_current_chat(*args, **kwargs):
        return None

    async def fake_list_custom_point_types(session, chat_id: int):
        return []

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "list_custom_point_types", fake_list_custom_point_types)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_custom_points_menu(update, context, -1001)

    assert rendered
    assert "0 条数据，第 1 页/共 1 页" in rendered[0]
