from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.garage.services.garage_features_service import TeacherSearchService


class _SessionContext:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commits += 1


class _FakeDb:
    def __init__(self, session: _SessionContext) -> None:
        self._session = session

    def session_factory(self):
        return self._session


@pytest.mark.asyncio
async def test_teacher_search_home_layout_matches_doc(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_safe_edit(update, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(
            tag_search_enabled=True,
            attendance_enabled=False,
            nearby_search_enabled=False,
            force_location_enabled=True,
            delete_mode="none",
            footer_button_label=None,
        )

    async def fake_list_open_course_teachers(session, chat_id: int):
        return [(SimpleNamespace(user_id=1), SimpleNamespace(username="teacher_a"))] * 2

    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)
    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_setting)
    monkeypatch.setattr(
        TeacherSearchService,
        "list_open_course_teachers",
        fake_list_open_course_teachers,
    )

    await admin_handler._admin_handler._show_teacher_search_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in captured["keyboard"]]
    assert rows == [
        ["标签搜索：", "✅ 启动", "关闭"],
        ["开课打卡：", "启动", "✅ 关闭"],
        ["附近搜索：", "启动", "✅ 关闭"],
        ["底部按钮：", "无"],
        ["删除消息：", "不删除"],
        ["📍 代录老师位置"],
        ["返回"],
    ]
    assert "强制录入：✅ 启动" in captured["text"]
    assert "开课老师：2 人" in captured["text"]
    assert "📚 开课老师" not in {button for row in rows for button in row}


@pytest.mark.asyncio
async def test_teacher_search_attendance_menu_keeps_force_and_open_teacher_entry(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_safe_edit(update, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(
            attendance_enabled=True,
            force_location_enabled=False,
        )

    async def fake_list_open_course_teachers(session, chat_id: int):
        return [(SimpleNamespace(user_id=1), SimpleNamespace(username="teacher_a"))]

    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)
    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_setting)
    monkeypatch.setattr(
        TeacherSearchService,
        "list_open_course_teachers",
        fake_list_open_course_teachers,
    )

    await admin_handler._admin_handler._show_teacher_search_attendance_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in captured["keyboard"]]
    assert rows == [
        ["强制录入：", "启动", "✅ 关闭"],
        ["📚 开课老师", "1 人"],
        ["返回"],
    ]
    assert "开课打卡：✅ 启动" in captured["text"]
    assert "强制录入：❌ 关闭" in captured["text"]
