from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.garage.teacher_search_inputs import handle_teacher_search_feature_input
from backend.features.garage.services.garage_features_service import TeacherSearchFooterButtonConfig, TeacherSearchService
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.base import ValidationError


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


def test_teacher_search_footer_config_reports_configured_state():
    empty = TeacherSearchFooterButtonConfig(button_text=None, button_url=None)
    by_text = TeacherSearchFooterButtonConfig(button_text="老师搜索", button_url=None)
    by_url = TeacherSearchFooterButtonConfig(button_text=None, button_url="https://example.com")

    assert empty.is_configured is False
    assert by_text.is_configured is True
    assert by_url.is_configured is True


@pytest.mark.asyncio
async def test_teacher_search_footer_service_rejects_non_http_url():
    with pytest.raises(ValidationError):
        await TeacherSearchService.update_footer_button_url(object(), -1001, "ftp://example.com")


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
    assert captured["keyboard"][3][1].callback_data == "tsearch:footer:menu:-1001"
    assert "强制录入：✅ 启动" in captured["text"]
    assert "底部按钮：无" in captured["text"]
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


@pytest.mark.asyncio
async def test_teacher_search_footer_menu_shows_text_and_link(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_safe_edit(update, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_footer_config(session, chat_id: int):
        return SimpleNamespace(
            button_text="老师搜索",
            button_url="https://example.com/h5/teacher-search",
            is_configured=True,
        )

    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)
    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(TeacherSearchService, "get_footer_button_config", fake_get_footer_config)

    await admin_handler._admin_handler._show_teacher_search_footer_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in captured["keyboard"]]
    assert "🔍 老师搜索 | 底部按钮" in captured["text"]
    assert "按钮文字：老师搜索" in captured["text"]
    assert "按钮链接：https://example.com/h5/teacher-search" in captured["text"]
    assert rows == [["修改文字"], ["修改链接"], ["⬅️ 返回"]]
    assert captured["keyboard"][0][0].callback_data == "tsearch:footer:text:-1001"
    assert captured["keyboard"][1][0].callback_data == "tsearch:footer:link:-1001"
    assert captured["keyboard"][2][0].callback_data == "tsearch:home:-1001"


@pytest.mark.asyncio
async def test_teacher_search_footer_menu_shows_unconfigured_values(monkeypatch):
    captured: dict[str, object] = {}
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_SessionContext())}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_safe_edit(update, text, reply_markup):
        captured["text"] = text

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_footer_config(session, chat_id: int):
        return SimpleNamespace(button_text=None, button_url=None, is_configured=False)

    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)
    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(TeacherSearchService, "get_footer_button_config", fake_get_footer_config)

    await admin_handler._admin_handler._show_teacher_search_footer_menu(update, context, -1001)

    assert "按钮文字：【未配置】" in captured["text"]
    assert "按钮链接：【未配置】" in captured["text"]


@pytest.mark.asyncio
async def test_teacher_search_footer_text_button_starts_text_state(monkeypatch):
    captured: dict[str, object] = {}
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_SessionContext())}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_start_text_input_state(context, user_id, state_chat_id, state_type, payload):
        captured["state"] = (user_id, state_chat_id, state_type, payload)

    async def fake_safe_edit(update, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        CallbackParser.parse("tsearch:footer:text:-1001"),
    )

    assert captured["state"] == (
        123,
        -1001,
        "teacher_footer_text_input",
        {"target_chat_id": -1001},
    )
    assert "请输入按钮名称" in captured["text"]
    assert captured["keyboard"][0][0].callback_data == "tsearch:footer:menu:-1001"


@pytest.mark.asyncio
async def test_teacher_search_footer_link_button_starts_link_state(monkeypatch):
    captured: dict[str, object] = {}
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_SessionContext())}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_start_text_input_state(context, user_id, state_chat_id, state_type, payload):
        captured["state"] = (user_id, state_chat_id, state_type, payload)

    async def fake_safe_edit(update, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        CallbackParser.parse("tsearch:footer:link:-1001"),
    )

    assert captured["state"] == (
        123,
        -1001,
        "teacher_footer_link_input",
        {"target_chat_id": -1001},
    )
    assert "请输入 H5 页面链接" in captured["text"]
    assert captured["keyboard"][0][0].callback_data == "tsearch:footer:menu:-1001"


@pytest.mark.asyncio
async def test_teacher_search_footer_text_input_updates_label(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_footer_text_input")

    async def fake_update_footer_text(session, chat_id, button_text):
        captured["setting"] = (chat_id, button_text)
        return SimpleNamespace(button_text=button_text, button_url=None, is_configured=True)

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(TeacherSearchService, "update_footer_button_text", fake_update_footer_text)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_footer_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state,
        -1001,
        "车库入口",
    )

    assert handled is True
    assert captured["setting"] == (-1001, "车库入口")
    assert captured["cleared"] == (-1001, 123)
    assert session.commits == 1
    assert captured["replies"] == ["已设置底部按钮文字：车库入口"]
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_footer_link_input_updates_url(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_footer_link_input")

    async def fake_update_footer_url(session, chat_id, button_url):
        captured["setting"] = (chat_id, button_url)
        return SimpleNamespace(button_text=None, button_url=button_url, is_configured=True)

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(TeacherSearchService, "update_footer_button_url", fake_update_footer_url)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_footer_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state,
        -1001,
        "https://example.com/h5/teacher-search",
    )

    assert handled is True
    assert captured["setting"] == (-1001, "https://example.com/h5/teacher-search")
    assert captured["cleared"] == (-1001, 123)
    assert session.commits == 1
    assert captured["replies"] == ["已设置底部按钮链接：https://example.com/h5/teacher-search"]
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_footer_link_input_rejects_invalid_url(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_footer_link_input")

    async def fake_update_footer_url(session, chat_id, button_url):
        raise ValidationError("按钮链接必须以 http:// 或 https:// 开头。")

    monkeypatch.setattr(TeacherSearchService, "update_footer_button_url", fake_update_footer_url)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state,
        -1001,
        "ftp://example.com",
    )

    assert handled is True
    assert captured["replies"] == ["按钮链接必须以 http:// 或 https:// 开头。"]
    assert session.commits == 0


@pytest.mark.asyncio
async def test_teacher_search_footer_text_input_clear(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_footer_text_input")

    async def fake_update_footer_text(session, chat_id, button_text):
        captured["setting"] = (chat_id, button_text)
        return SimpleNamespace(button_text=None, button_url="https://example.com", is_configured=True)

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(TeacherSearchService, "update_footer_button_text", fake_update_footer_text)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_footer_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state,
        -1001,
        "/clear",
    )

    assert handled is True
    assert captured["setting"] == (-1001, None)
    assert captured["replies"] == ["已清空底部按钮文字。"]
    assert captured["shown"] == -1001
