from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.garage.teacher_self import (
    handle_teacher_self_input,
    teacher_self_callback,
)
from backend.features.admin.garage.teacher_search_inputs import (
    handle_teacher_member_location_input,
    handle_teacher_search_feature_input,
)
from backend.features.garage.services.garage_features_service import GarageAuthService, TeacherSearchFooterButtonConfig, TeacherSearchService
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.base import ValidationError


class _SessionContext:
    def __init__(self, get_map=None) -> None:
        self.commits = 0
        self.get_map = dict(get_map or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commits += 1

    async def get(self, model, key):
        return self.get_map.get((model, key))


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
    assert by_url.is_configured is False


@pytest.mark.asyncio
async def test_garage_clear_admin_input_state_preserves_private_selected_chat(monkeypatch):
    from backend.features.admin.garage.input_runtime import clear_admin_input_state

    calls: list[tuple] = []

    async def fake_clear_user_state(session, chat_id: int, user_id: int):
        calls.append(("clear", chat_id, user_id))

    async def fake_clear_private_input_state(session, user_id: int):
        calls.append(("clear_private_input", user_id))

    monkeypatch.setattr("backend.platform.state.state_service.clear_user_state", fake_clear_user_state)
    monkeypatch.setattr("backend.platform.state.state_service.clear_private_input_state", fake_clear_private_input_state)

    await clear_admin_input_state(object(), target_chat_id=-1001, user_id=123)

    assert calls == [("clear", -1001, 123), ("clear_private_input", 123)]


@pytest.mark.asyncio
async def test_teacher_search_footer_service_ignores_legacy_url(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_update_setting(session, chat_id: int, **updates):
        captured["updates"] = updates
        return SimpleNamespace(footer_button_label="老师搜索", footer_button_url=updates.get("footer_button_url"))

    monkeypatch.setattr(
        "backend.features.garage.services.teacher_search_settings.TeacherSearchSettingsMixin.update_setting",
        fake_update_setting,
    )

    config = await TeacherSearchService.update_footer_button_url(object(), -1001, "ftp://example.com")

    assert captured["updates"] == {"footer_button_url": None}
    assert config.button_text == "老师搜索"
    assert config.button_url is None


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
            only_open_course_enabled=True,
            attendance_enabled=False,
            attendance_mode="message",
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
        ["删除消息：", "不删除"],
        ["📍 代录老师位置"],
        ["返回"],
    ]
    assert all("打卡模式：" not in row for row in rows)
    assert all("只显开课：" not in row for row in rows)
    assert all("📝 手动替老师打卡" not in row for row in rows)
    assert all("强制录入：" not in row for row in rows)
    assert all("底部按钮：" not in row for row in rows)
    assert "强制录入：✅ 启动" not in captured["text"]
    assert "只显开课：✅ 启动" not in captured["text"]
    assert "打卡模式：发言就是打卡" not in captured["text"]
    assert "底部按钮：无" not in captured["text"]
    assert "开课老师：2 人" in captured["text"]
    assert "📚 开课老师" not in {button for row in rows for button in row}


@pytest.mark.asyncio
async def test_teacher_search_home_shows_dependent_rows_after_parent_enabled(monkeypatch):
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
            only_open_course_enabled=False,
            attendance_enabled=True,
            attendance_mode="message",
            nearby_search_enabled=True,
            force_location_enabled=False,
            delete_mode="none",
            footer_button_label=None,
        )

    async def fake_list_open_course_teachers(session, chat_id: int):
        return []

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
        ["开课打卡：", "✅ 启动", "关闭"],
        ["打卡模式：", "发言就是打卡"],
        ["只显开课：", "启动", "✅ 关闭"],
        ["📝 手动替老师打卡"],
        ["附近搜索：", "✅ 启动", "关闭"],
        ["强制录入：", "启动", "✅ 关闭"],
        ["删除消息：", "不删除"],
        ["📍 代录老师位置"],
        ["返回"],
    ]
    assert captured["keyboard"][2][1].callback_data == "tsearch:attendance_mode:menu:-1001"
    assert captured["keyboard"][4][0].callback_data == "tsearch:attendance:manual:-1001"
    assert "强制录入：❌ 关闭" in captured["text"]
    assert "只显开课：❌ 关闭" in captured["text"]
    assert "打卡模式：发言就是打卡" in captured["text"]


@pytest.mark.asyncio
async def test_teacher_search_attendance_menu_hides_force_when_nearby_is_off(monkeypatch):
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
            nearby_search_enabled=False,
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
        ["📚 开课老师", "1 人"],
        ["返回"],
    ]
    assert "开课打卡：✅ 启动" in captured["text"]
    assert "强制录入：❌ 关闭" not in captured["text"]


@pytest.mark.asyncio
async def test_teacher_search_attendance_mode_menu_shows_fixed_words(monkeypatch):
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
            attendance_mode="keyword",
            attendance_source_chat_id=None,
            attendance_open_keyword="开课",
            attendance_full_keyword="满课",
            attendance_rest_keyword="休息",
        )

    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)
    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_setting)

    await admin_handler._admin_handler._show_teacher_search_attendance_mode_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in captured["keyboard"]]
    assert "🔍 老师搜索 | 选择打卡模式" in captured["text"]
    assert rows[:3] == [["不在此群打卡"], ["发言就是打卡"], ["✅ 固定话术打卡"]]
    assert rows[3:6] == [["🟡 开课词：", "开课"], ["🔴 满课词：", "满课"], ["⚪ 休息词：", "休息"]]
    assert captured["keyboard"][0][0].callback_data == "tsearch:attendance_source:menu:-1001"
    assert captured["keyboard"][3][1].callback_data == "tsearch:attendance_word:open:-1001"


@pytest.mark.asyncio
async def test_teacher_search_footer_menu_shows_text_without_link(monkeypatch):
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
    assert "按钮链接" not in captured["text"]
    assert "点击底部按钮会直接发送这个文字" in captured["text"]
    assert rows == [["修改文字"], ["⬅️ 返回"]]
    assert captured["keyboard"][0][0].callback_data == "tsearch:footer:text:-1001"
    assert captured["keyboard"][1][0].callback_data == "tsearch:home:-1001"


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
    assert "按钮链接" not in captured["text"]


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
        callback_data=CallbackParser.parse("tsearch:footer:text:-1001"),
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
async def test_teacher_search_footer_link_button_returns_to_text_only_menu(monkeypatch):
    captured: dict[str, object] = {}
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_SessionContext())}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), callback_query=SimpleNamespace())

    async def fake_answer(update, text, **kwargs):
        captured["answer"] = text

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    monkeypatch.setattr("backend.features.admin.garage.teacher_search_actions.answer_callback_query_safely", fake_answer)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_footer_menu", fake_show_menu)

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("tsearch:footer:link:-1001"),
    )

    assert captured["answer"] == "底部按钮不需要配置链接，点击后会直接触发老师搜索。"
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_delegate_button_starts_short_target_state(monkeypatch):
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
        callback_data=CallbackParser.parse("tsearch:delegate:start:-1001"),
    )

    assert captured["state"] == (
        123,
        -1001,
        "teacher_delegate_target_input",
        {"target_chat_id": -1001},
    )
    assert "请输入上牌老师的用户名或ID" in captured["text"]


@pytest.mark.asyncio
async def test_teacher_search_attendance_manual_button_starts_short_target_state(monkeypatch):
    captured: dict[str, object] = {}
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_SessionContext())}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_start_text_input_state(context, user_id, state_chat_id, state_type, payload):
        captured["state"] = (user_id, state_chat_id, state_type, payload)

    async def fake_safe_edit(update, text, reply_markup):
        captured["text"] = text

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("tsearch:attendance:manual:-1001"),
    )

    assert captured["state"] == (
        123,
        -1001,
        "teacher_attend_target_input",
        {"target_chat_id": -1001},
    )
    assert "手动替老师打卡" in captured["text"]


@pytest.mark.asyncio
async def test_teacher_search_attendance_mode_callback_updates_setting(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_update_setting(session, chat_id, **updates):
        captured["updates"] = (chat_id, updates)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    monkeypatch.setattr(TeacherSearchService, "update_setting", fake_update_setting)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_attendance_mode_menu", fake_show_menu)

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("tsearch:attendance_mode:set:-1001:keyword"),
    )

    assert captured["updates"] == (-1001, {"attendance_mode": "keyword"})
    assert session.commits == 1
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_attendance_source_set_opens_source_mode_page(monkeypatch):
    captured: dict[str, object] = {}
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_SessionContext())}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_require_manage(context, chat_id, user_id, capability):
        captured["permission"] = (chat_id, user_id, capability)
        return True, None

    async def fake_show_source_mode(update, context, chat_id, source_chat_id):
        captured["source_mode_page"] = (chat_id, source_chat_id)

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(
        admin_handler._admin_handler,
        "_show_teacher_search_attendance_source_mode_menu",
        fake_show_source_mode,
    )

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("tsearch:attendance_source:set:-1001:-2002"),
    )

    assert captured["permission"] == (-2002, 123, "manage")
    assert captured["source_mode_page"] == (-1001, -2002)


@pytest.mark.asyncio
async def test_teacher_search_attendance_source_mode_callback_links_group_and_sets_source_mode(monkeypatch):
    captured: dict[str, object] = {"updates": []}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_require_manage(context, chat_id, user_id, capability):
        captured["permission"] = (chat_id, user_id, capability)
        return True, None

    async def fake_update_setting(session, chat_id, **updates):
        captured["updates"].append((chat_id, updates))

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(TeacherSearchService, "update_setting", fake_update_setting)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_attendance_mode_menu", fake_show_menu)

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("tsearch:attendance_source_mode:set:-1001:-2002:keyword"),
    )

    assert captured["permission"] == (-2002, 123, "manage")
    assert captured["updates"] == [
        (-1001, {"attendance_mode": "external", "attendance_source_chat_id": -2002}),
        (-2002, {"attendance_enabled": True, "attendance_mode": "keyword"}),
    ]
    assert session.commits == 1
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_force_location_toggle_enables_nearby(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))

    async def fake_update_setting(session, chat_id, **updates):
        captured["updates"] = (chat_id, updates)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    monkeypatch.setattr(TeacherSearchService, "update_setting", fake_update_setting)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_menu", fake_show_menu)

    await admin_handler._admin_handler._handle_teacher_search(
        update,
        context,
        -1001,
        callback_data=CallbackParser.parse("tsearch:toggle:force_loc:-1001:1"),
    )

    assert captured["updates"] == (
        -1001,
        {"force_location_enabled": True, "nearby_search_enabled": True},
    )
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_footer_text_input_updates_label(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured.setdefault("reply_markups", []).append(kwargs.get("reply_markup"))

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
        state=state,
        target_chat_id=-1001,
        text_value="车库入口",
    )

    assert handled is True
    assert captured["setting"] == (-1001, "车库入口")
    assert captured["cleared"] == (-1001, 123)
    assert session.commits == 1
    assert captured["replies"] == ["已设置底部按钮文字：车库入口"]
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_footer_link_input_clears_legacy_state(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured.setdefault("reply_markups", []).append(kwargs.get("reply_markup"))

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_footer_link_input")

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_footer_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="https://example.com/h5/teacher-search",
    )

    assert handled is True
    assert captured["cleared"] == (-1001, 123)
    assert session.commits == 1
    assert captured["replies"] == ["底部按钮不需要配置链接，点击后会直接触发老师搜索。"]
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_location_start_sets_private_location_state(monkeypatch):
    from backend.features.group_ops import start_handler
    from backend.platform.db.schema.models.core import TgChat
    from backend.platform.db.schema.models.garage_features import TeacherSearchSetting

    captured: dict[str, object] = {"replies": []}
    session = _SessionContext(
        get_map={
            (TgChat, -1001): SimpleNamespace(id=-1001, title="测试群"),
            (TeacherSearchSetting, -1001): SimpleNamespace(nearby_search_enabled=True),
        }
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    class _Message:
        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured["reply_markup"] = kwargs.get("reply_markup")

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())

    async def fake_set_user_state(session, chat_id, user_id, state_type, state_data):
        captured["state"] = (chat_id, user_id, state_type, state_data)

    async def fake_get_user_state(*args, **kwargs):
        return SimpleNamespace(
            state_type="selected_chat",
            state_data={"managed_chat_id": -2002},
        )

    monkeypatch.setattr(start_handler, "set_user_state", fake_set_user_state)
    monkeypatch.setattr(start_handler, "get_user_state", fake_get_user_state)

    handled = await start_handler._handle_teacher_location_start(update, context, "tloc_-1001")

    assert handled is True
    assert captured["state"] == (
        123,
        123,
        "teacher_member_location_input",
        {"target_chat_id": -1001, "previous_selected_chat_id": -2002},
    )
    assert session.commits == 1
    assert "目标群：测试群" in captured["replies"][0]
    assert "不会在群里公开" in captured["replies"][0]


@pytest.mark.asyncio
async def test_teacher_self_location_start_sets_teacher_service_state(monkeypatch):
    from backend.features.group_ops import start_handler
    from backend.platform.db.schema.models.core import TgChat

    captured: dict[str, object] = {"replies": []}
    session = _SessionContext(
        get_map={
            (TgChat, -1001): SimpleNamespace(id=-1001, title="测试群"),
        }
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    class _Message:
        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured["reply_markup"] = kwargs.get("reply_markup")

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())

    async def fake_set_user_state(session, chat_id, user_id, state_type, state_data):
        captured["state"] = (chat_id, user_id, state_type, state_data)

    async def fake_is_teacher(session, chat_id: int, user_id: int):
        return True

    monkeypatch.setattr(start_handler, "set_user_state", fake_set_user_state)
    monkeypatch.setattr(GarageAuthService, "is_effective_certified_teacher", fake_is_teacher)

    handled = await start_handler._handle_teacher_self_location_start(update, context, "tselfloc_-1001")

    assert handled is True
    assert captured["state"] == (
        123,
        123,
        "teacher_self_location_input",
        {"target_chat_id": -1001},
    )
    assert session.commits == 1
    assert "目标群：测试群" in captured["replies"][0]
    assert "不会覆盖你的群友附近查询定位" in captured["replies"][0]


@pytest.mark.asyncio
async def test_teacher_member_location_input_only_saves_member_location(monkeypatch):
    from backend.platform.db.schema.models.garage_features import TeacherSearchSetting

    captured: dict[str, object] = {"replies": [], "calls": []}
    session = _SessionContext(
        get_map={(TeacherSearchSetting, -1001): SimpleNamespace(nearby_search_enabled=True)}
    )
    context = SimpleNamespace()

    class _Message:
        message_id = 9
        location = SimpleNamespace(latitude=31.2, longitude=121.4)
        venue = None

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured["reply_markup"] = kwargs.get("reply_markup")

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(
        chat_id=123,
        state_type="teacher_member_location_input",
        state_data={"target_chat_id": -1001, "previous_selected_chat_id": -2002},
    )

    async def fake_upsert_member_location(session, **kwargs):
        captured["calls"].append(("member", kwargs))

    async def fake_clear_user_state(session, chat_id, user_id):
        captured["cleared"] = (chat_id, user_id)

    async def fake_set_user_state(session, chat_id, user_id, state_type, state_data):
        captured["restored"] = (chat_id, user_id, state_type, state_data)

    monkeypatch.setattr(TeacherSearchService, "upsert_member_location", fake_upsert_member_location)
    monkeypatch.setattr("backend.platform.state.state_service.clear_user_state", fake_clear_user_state)
    monkeypatch.setattr("backend.platform.state.state_service.set_user_state", fake_set_user_state)

    await handle_teacher_member_location_input(update, context, session, state=state, message_text="")

    assert captured["cleared"] == (123, 123)
    assert captured["restored"] == (123, 123, "selected_chat", {"managed_chat_id": -2002})
    assert session.commits == 1
    assert captured["calls"] == [
        (
            "member",
            {
                "chat_id": -1001,
                "user_id": 123,
                "latitude": 31.2,
                "longitude": 121.4,
                "operator_user_id": 123,
            },
        ),
    ]
    assert captured["replies"] == ["✅ 定位已更新。回到群里发送“附近”即可查询附近老师。"]


@pytest.mark.asyncio
async def test_teacher_self_callback_shows_group_list(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    async def fake_list_teacher_self_chats(session, user_id: int):
        return [
            (
                SimpleNamespace(id=-1001, title="测试群"),
                SimpleNamespace(display_text="本群认证池"),
            )
        ]

    async def fake_safe_edit(update, text, reply_markup=None):
        captured["text"] = text
        captured["reply_markup"] = reply_markup

    monkeypatch.setattr(GarageAuthService, "list_teacher_self_service_chats", fake_list_teacher_self_chats)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(data="teacher:self:list"),
    )

    await teacher_self_callback(update, context)

    assert "老师资料维护" in captured["text"]
    keyboard = captured["reply_markup"].inline_keyboard
    assert keyboard[0][0].callback_data == "teacher:self:home:-1001"


@pytest.mark.asyncio
async def test_teacher_self_home_button_shows_group_profile(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    async def fake_is_teacher(session, chat_id: int, user_id: int):
        return True

    async def fake_get_teacher_profile(session, chat_id: int, user_id: int):
        return SimpleNamespace(
            latitude=31.2,
            longitude=121.4,
            region_text="浦东",
            price_text="300",
            labels=["热门", "夜课"],
        )

    async def fake_get_pool_info(session, chat_id: int):
        return SimpleNamespace(display_text="本群认证池")

    async def fake_resolve_chat_title(context, chat_id: int):
        return "测试群"

    async def fake_safe_edit(update, text, reply_markup=None):
        captured["text"] = text
        captured["reply_markup"] = reply_markup

    monkeypatch.setattr(GarageAuthService, "is_effective_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(TeacherSearchService, "get_teacher_profile", fake_get_teacher_profile)
    monkeypatch.setattr(GarageAuthService, "get_teacher_pool_info", fake_get_pool_info)
    monkeypatch.setattr("backend.features.admin.garage.teacher_self._resolve_chat_title", fake_resolve_chat_title)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(data="teacher:self:home:-1001"),
    )

    await teacher_self_callback(update, context)

    assert "群组：测试群" in captured["text"]
    assert "服务定位：已设置" in captured["text"]
    assert "老师本人仅可更新服务定位" in captured["text"]
    callbacks = [button.callback_data for row in captured["reply_markup"].inline_keyboard for button in row]
    assert "teacher:self:location:-1001" in callbacks
    assert "teacher:self:region:-1001" not in callbacks
    assert "teacher:self:price:-1001" not in callbacks
    assert "teacher:self:labels:-1001" not in callbacks


@pytest.mark.asyncio
async def test_teacher_self_location_button_starts_location_state(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    async def fake_is_teacher(session, chat_id: int, user_id: int):
        return True

    async def fake_start_text_input_state(context, chat_id: int, user_id: int, *, state_type: str, payload: dict):
        captured["state"] = (chat_id, user_id, state_type, payload)

    async def fake_safe_edit(update, text, reply_markup=None):
        captured["text"] = text
        captured["reply_markup"] = reply_markup

    monkeypatch.setattr(GarageAuthService, "is_effective_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(data="teacher:self:location:-1001"),
    )

    await teacher_self_callback(update, context)

    assert captured["state"] == (
        123,
        123,
        "teacher_self_location_input",
        {"target_chat_id": -1001},
    )
    assert "更新服务定位" in captured["text"]
    assert captured["reply_markup"].inline_keyboard[0][0].callback_data == "teacher:self:home:-1001"


@pytest.mark.asyncio
async def test_teacher_self_profile_edit_buttons_are_blocked(monkeypatch):
    captured: dict[str, object] = {}
    session = _SessionContext()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    async def fake_is_teacher(session, chat_id: int, user_id: int):
        return True

    async def fake_safe_edit(update, text, reply_markup=None):
        captured["text"] = text
        captured["reply_markup"] = reply_markup

    monkeypatch.setattr(GarageAuthService, "is_effective_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(data="teacher:self:price:-1001"),
    )

    await teacher_self_callback(update, context)

    assert "老师本人仅可更新服务定位" in captured["text"]
    assert captured["reply_markup"].inline_keyboard[0][0].callback_data == "teacher:self:home:-1001"


@pytest.mark.asyncio
async def test_start_private_home_markup_adds_teacher_entry(monkeypatch):
    from backend.features.group_ops import start_handler

    async def fake_list_teacher_self_chats(context, user_id: int):
        return [(SimpleNamespace(id=-1001, title="测试群"), SimpleNamespace())]

    monkeypatch.setattr(start_handler, "_list_teacher_self_chats", fake_list_teacher_self_chats)

    markup = await start_handler._build_private_home_markup(
        SimpleNamespace(),
        user_id=123,
        chats=[(-2001, "管理群", True)],
        current_chat_id=-2001,
    )

    labels = [button.text for row in markup.inline_keyboard for button in row]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "👩‍🏫 老师资料维护" in labels
    assert "teacher:self:list" in callbacks


@pytest.mark.asyncio
async def test_teacher_self_location_input_updates_teacher_profile_only(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        location = SimpleNamespace(latitude=31.2, longitude=121.4)
        venue = None

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(
        chat_id=123,
        state_type="teacher_self_location_input",
        state_data={"target_chat_id": -1001},
    )

    async def fake_is_teacher(session, chat_id: int, user_id: int):
        return True

    async def fake_upsert_teacher_profile(session, **kwargs):
        captured["teacher_profile"] = kwargs

    async def fake_clear_user_state(session, chat_id: int, user_id: int):
        captured["cleared"] = (chat_id, user_id)

    async def fake_show_home(update, context, chat_id: int):
        captured["shown"] = chat_id

    monkeypatch.setattr(GarageAuthService, "is_effective_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(TeacherSearchService, "upsert_teacher_profile_from_location", fake_upsert_teacher_profile)
    monkeypatch.setattr("backend.features.admin.garage.teacher_self.clear_user_state", fake_clear_user_state)
    monkeypatch.setattr("backend.features.admin.garage.teacher_self.show_teacher_self_home", fake_show_home)

    await handle_teacher_self_input(update, context, session, state=state, message_text="")

    assert captured["teacher_profile"] == {
        "chat_id": -1001,
        "user_id": 123,
        "latitude": 31.2,
        "longitude": 121.4,
    }
    assert captured["cleared"] == (123, 123)
    assert session.commits == 1
    assert captured["replies"] == ["✅ 已更新该群的服务定位。"]
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_attendance_target_input_marks_teacher(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        message_id = 88

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_attend_target_input")
    teacher = SimpleNamespace(id=456, username="teacher_a")

    async def fake_resolve_user(session, raw):
        captured["resolved"] = raw
        return teacher

    async def fake_is_certified(session, chat_id, user_id):
        captured["certified_lookup"] = (chat_id, user_id)
        return True

    async def fake_mark_attendance(session, *, chat_id, user_id, source_message_id):
        captured["attendance"] = (chat_id, user_id, source_message_id)

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(TeacherSearchService, "resolve_delegate_user", fake_resolve_user)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_certified)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="@teacher_a",
    )

    assert handled is True
    assert captured["resolved"] == "@teacher_a"
    assert captured["certified_lookup"] == (-1001, 456)
    assert captured["attendance"] == (-1001, 456, 88)
    assert captured["cleared"] == (-1001, 123)
    assert session.commits == 1
    assert captured["replies"] == ["✅ 已替 @teacher_a 记录今日开课打卡。"]
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_footer_link_input_ignores_invalid_url(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_footer_link_input")

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_footer_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="ftp://example.com",
    )

    assert handled is True
    assert captured["cleared"] == (-1001, 123)
    assert captured["replies"] == ["底部按钮不需要配置链接，点击后会直接触发老师搜索。"]
    assert captured["shown"] == -1001
    assert session.commits == 1


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
        state=state,
        target_chat_id=-1001,
        text_value="/clear",
    )

    assert handled is True
    assert captured["setting"] == (-1001, None)
    assert captured["replies"] == ["已清空底部按钮文字。"]
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_delegate_target_input_starts_short_location_state(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured.setdefault("reply_markups", []).append(kwargs.get("reply_markup"))

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(state_type="teacher_delegate_target_input")

    async def fake_resolve_delegate_user(session, raw_value):
        captured["resolved"] = raw_value
        return SimpleNamespace(id=456)

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_set_user_state(session, chat_id, user_id, state_type, state_data):
        captured["state"] = (chat_id, user_id, state_type, state_data)

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs
    import backend.platform.state.state_service as state_service

    monkeypatch.setattr(TeacherSearchService, "resolve_delegate_user", fake_resolve_delegate_user)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(state_service, "set_user_state", fake_set_user_state)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="@teacher_a",
    )

    assert handled is True
    assert captured["resolved"] == "@teacher_a"
    assert captured["cleared"] == (-1001, 123)
    assert captured["state"] == (
        -1001,
        123,
        "teacher_delegate_location_input",
        {"target_chat_id": -1001, "delegate_user_id": 456},
    )
    assert session.commits == 1
    assert captured["replies"] == [
        (
            "📍 请发送这位老师的位置。\n\n"
            "手机端可以直接发送位置；桌面端请点输入框旁的回形针 → 位置 → 在地图上选择/搜索地点后发送。\n"
            "也可以粘贴 Google 地图定位链接。\n"
            "不要手动输入经纬度。"
        )
    ]
    assert captured["reply_markups"][0].to_dict() == {"remove_keyboard": True}


@pytest.mark.asyncio
async def test_teacher_search_delegate_location_input_requires_location_message():
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        location = None
        venue = None

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured["reply_markup"] = kwargs.get("reply_markup")

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(
        state_type="teacher_delegate_location_input",
        state_data={"target_chat_id": -1001, "delegate_user_id": 456},
    )

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="39.1,116.1",
    )

    assert handled is True
    assert captured["replies"] == ["请通过回形针 → 位置 发送地点，或粘贴 Google 地图定位链接。"]
    assert captured["reply_markup"].to_dict() == {"remove_keyboard": True}
    assert session.commits == 0


@pytest.mark.asyncio
async def test_teacher_search_delegate_location_input_saves_telegram_location(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        location = SimpleNamespace(latitude=39.9042, longitude=116.4074)
        venue = None

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)
            captured.setdefault("reply_markups", []).append(kwargs.get("reply_markup"))

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(
        state_type="teacher_delegate_location_input",
        state_data={"target_chat_id": -1001, "delegate_user_id": 456},
    )

    async def fake_upsert_member_location(session, **kwargs):
        captured["member_location"] = kwargs

    async def fake_upsert_teacher_profile(session, **kwargs):
        captured["teacher_profile"] = kwargs

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(TeacherSearchService, "upsert_member_location", fake_upsert_member_location)
    monkeypatch.setattr(TeacherSearchService, "upsert_teacher_profile_from_location", fake_upsert_teacher_profile)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="",
    )

    assert handled is True
    assert captured["member_location"] == {
        "chat_id": -1001,
        "user_id": 456,
        "latitude": 39.9042,
        "longitude": 116.4074,
        "operator_user_id": 123,
    }
    assert captured["teacher_profile"] == {
        "chat_id": -1001,
        "user_id": 456,
        "latitude": 39.9042,
        "longitude": 116.4074,
    }
    assert captured["cleared"] == (-1001, 123)
    assert captured["replies"] == ["✅ 已为该老师录入位置。"]
    assert captured["shown"] == -1001
    assert session.commits == 1


@pytest.mark.asyncio
async def test_teacher_search_delegate_location_input_saves_shared_map_venue(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        location = None
        venue = SimpleNamespace(location=SimpleNamespace(latitude=31.2304, longitude=121.4737))

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(
        state_type="teacher_delegate_location_input",
        state_data={"target_chat_id": -1001, "delegate_user_id": 456},
    )

    async def fake_upsert_member_location(session, **kwargs):
        captured["member_location"] = kwargs

    async def fake_upsert_teacher_profile(session, **kwargs):
        captured["teacher_profile"] = kwargs

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(TeacherSearchService, "upsert_member_location", fake_upsert_member_location)
    monkeypatch.setattr(TeacherSearchService, "upsert_teacher_profile_from_location", fake_upsert_teacher_profile)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="",
    )

    assert handled is True
    assert captured["member_location"]["latitude"] == 31.2304
    assert captured["member_location"]["longitude"] == 121.4737
    assert captured["teacher_profile"]["latitude"] == 31.2304
    assert captured["teacher_profile"]["longitude"] == 121.4737
    assert captured["cleared"] == (-1001, 123)
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_delegate_location_input_saves_google_maps_link(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        location = None
        venue = None

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(
        state_type="teacher_delegate_location_input",
        state_data={"target_chat_id": -1001, "delegate_user_id": 456},
    )

    async def fake_upsert_member_location(session, **kwargs):
        captured["member_location"] = kwargs

    async def fake_upsert_teacher_profile(session, **kwargs):
        captured["teacher_profile"] = kwargs

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(TeacherSearchService, "upsert_member_location", fake_upsert_member_location)
    monkeypatch.setattr(TeacherSearchService, "upsert_teacher_profile_from_location", fake_upsert_teacher_profile)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="https://www.google.com/maps/place/Test/@31.2304,121.4737,17z",
    )

    assert handled is True
    assert captured["member_location"]["latitude"] == 31.2304
    assert captured["member_location"]["longitude"] == 121.4737
    assert captured["teacher_profile"]["latitude"] == 31.2304
    assert captured["teacher_profile"]["longitude"] == 121.4737
    assert captured["cleared"] == (-1001, 123)
    assert captured["shown"] == -1001


@pytest.mark.asyncio
async def test_teacher_search_delegate_location_input_expands_short_google_maps_link(monkeypatch):
    captured: dict[str, object] = {"replies": []}
    session = _SessionContext()
    context = SimpleNamespace()

    class _Message:
        location = None
        venue = None

        async def reply_text(self, text, **kwargs):
            captured["replies"].append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=_Message())
    state = SimpleNamespace(
        state_type="teacher_delegate_location_input",
        state_data={"target_chat_id": -1001, "delegate_user_id": 456},
    )

    async def fake_expand_map_url(url):
        captured["expanded"] = url
        return "https://www.google.com/maps/search/?api=1&query=39.9042%2C116.4074"

    async def fake_upsert_member_location(session, **kwargs):
        captured["member_location"] = kwargs

    async def fake_upsert_teacher_profile(session, **kwargs):
        captured["teacher_profile"] = kwargs

    async def fake_clear_state(session, *, target_chat_id, user_id):
        captured["cleared"] = (target_chat_id, user_id)

    async def fake_show_menu(update, context, chat_id):
        captured["shown"] = chat_id

    import backend.features.admin.garage.teacher_search_inputs as teacher_search_inputs

    monkeypatch.setattr(teacher_search_inputs, "_expand_map_url", fake_expand_map_url)
    monkeypatch.setattr(TeacherSearchService, "upsert_member_location", fake_upsert_member_location)
    monkeypatch.setattr(TeacherSearchService, "upsert_teacher_profile_from_location", fake_upsert_teacher_profile)
    monkeypatch.setattr(teacher_search_inputs, "clear_admin_input_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_teacher_search_menu", fake_show_menu)

    handled = await handle_teacher_search_feature_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=-1001,
        text_value="https://maps.app.goo.gl/abc123",
    )

    assert handled is True
    assert captured["expanded"] == "https://maps.app.goo.gl/abc123"
    assert captured["member_location"]["latitude"] == 39.9042
    assert captured["member_location"]["longitude"] == 116.4074
    assert captured["teacher_profile"]["latitude"] == 39.9042
    assert captured["teacher_profile"]["longitude"] == 116.4074
    assert captured["cleared"] == (-1001, 123)
    assert captured["shown"] == -1001
