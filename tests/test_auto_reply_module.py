from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.error import BadRequest

from backend.features.moderation import auto_reply_handler
from backend.features.moderation.auto_reply_handler import (
    _extract_auto_reply_list_page,
    _format_auto_reply_rule_detail,
    _parse_auto_reply_buttons_input,
)
from backend.features.moderation.auto_reply_payloads import send_auto_reply_payload
from backend.features.moderation.ui.auto_reply import (
    auto_reply_delay_keyboard,
    auto_reply_detail_keyboard,
    auto_reply_list_keyboard,
    auto_reply_menu_keyboard,
)
from backend.features.moderation.services import auto_reply_service


class _FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0
        self.commit_count = 0

    def add(self, entity) -> None:
        self.added.append(entity)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeDb:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session_factory(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)


class _FakeCallbackQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []
        self.edits: list[str] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str, reply_markup=None, parse_mode=None) -> None:
        self.edits.append(text)


class _FakeAutoReplyBot:
    def __init__(self, *, fail_photo: bool = False, fail_message_with_reply: bool = False) -> None:
        self.fail_photo = fail_photo
        self.fail_message_with_reply = fail_message_with_reply
        self.calls: list[tuple[str, dict]] = []

    async def send_photo(self, **kwargs):
        self.calls.append(("send_photo", kwargs))
        if self.fail_photo:
            raise BadRequest("wrong file identifier")
        return SimpleNamespace(message_id=100)

    async def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        if self.fail_message_with_reply and kwargs.get("reply_to_message_id"):
            raise BadRequest("reply message not found")
        return SimpleNamespace(message_id=101)


@pytest.mark.asyncio
async def test_create_auto_reply_rule_sets_sort_and_delete_config(monkeypatch) -> None:
    session = _FakeSession()

    async def fake_get_next_sort_order(session, chat_id: int) -> int:
        return 5

    monkeypatch.setattr(auto_reply_service, "get_next_sort_order", fake_get_next_sort_order)

    result = await auto_reply_service.create_auto_reply_rule(
        session,
        chat_id=-100123,
        created_by_user_id=42,
        keywords=["hello", "hi"],
        reply_content="world",
        delete_source=True,
        delete_reply_delay_seconds=30,
        cover_media_type="photo",
        cover_media_file_id="file-1",
        buttons=[[{"text": "官网", "url": "https://example.com"}]],
        stop_after_match=False,
    )

    assert result.success is True
    assert result.entity.sort_order == 5
    assert result.entity.delete_source is True
    assert result.entity.delete_reply_delay_seconds == 30
    assert result.entity.cover_media_type == "photo"
    assert result.entity.cover_media_file_id == "file-1"
    assert result.entity.buttons == [[{"text": "官网", "url": "https://example.com"}]]
    assert result.entity.stop_after_match is False
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_create_auto_reply_rule_rejects_negative_delete_delay() -> None:
    session = _FakeSession()

    result = await auto_reply_service.create_auto_reply_rule(
        session,
        chat_id=-100123,
        created_by_user_id=42,
        keywords=["hello"],
        reply_content="world",
        delete_reply_delay_seconds=-1,
    )

    assert result.success is False
    assert result.reason == "invalid_delete_delay"


@pytest.mark.asyncio
async def test_update_auto_reply_rule_uses_chat_scope_when_provided(monkeypatch) -> None:
    session = _FakeSession()
    rule = SimpleNamespace(id=7, chat_id=-100123, keywords=["old"], reply_content="old")
    updates: list[dict] = []

    async def fake_get_scoped_rule(session, chat_id: int, rule_id: int):
        assert chat_id == -100123
        assert rule_id == 7
        return rule

    async def fake_get_global_rule(session, rule_id: int):
        raise AssertionError("global lookup should not be used when chat_id is provided")

    async def fake_update_entity(session, entity, payload):
        updates.append(payload)
        for key, value in payload.items():
            setattr(entity, key, value)

    monkeypatch.setattr(auto_reply_service, "get_auto_reply_rule_in_chat", fake_get_scoped_rule)
    monkeypatch.setattr(auto_reply_service, "get_auto_reply_rule", fake_get_global_rule)
    monkeypatch.setattr(auto_reply_service.ServiceBase, "_update_entity", fake_update_entity)

    result = await auto_reply_service.update_auto_reply_rule(
        session,
        7,
        chat_id=-100123,
        keywords=[" hello ", "world"],
        reply_content="new reply",
    )

    assert result is rule
    assert updates == [{"keywords": ["hello", "world"], "reply_content": "new reply"}]


@pytest.mark.asyncio
async def test_toggle_and_delete_auto_reply_rule_use_chat_scope_when_provided(monkeypatch) -> None:
    session = _FakeSession()
    rule = SimpleNamespace(id=7, chat_id=-100123, is_active=True)
    deleted = []

    async def fake_get_scoped_rule(session, chat_id: int, rule_id: int):
        assert chat_id == -100123
        assert rule_id == 7
        return rule

    async def fake_get_global_rule(session, rule_id: int):
        raise AssertionError("global lookup should not be used when chat_id is provided")

    async def fake_update_entity(session, entity, payload):
        for key, value in payload.items():
            setattr(entity, key, value)

    async def fake_delete_entity(session, entity):
        deleted.append(entity.id)

    monkeypatch.setattr(auto_reply_service, "get_auto_reply_rule_in_chat", fake_get_scoped_rule)
    monkeypatch.setattr(auto_reply_service, "get_auto_reply_rule", fake_get_global_rule)
    monkeypatch.setattr(auto_reply_service.ServiceBase, "_update_entity", fake_update_entity)
    monkeypatch.setattr(auto_reply_service.ServiceBase, "_delete_entity", fake_delete_entity)

    toggled = await auto_reply_service.toggle_auto_reply_rule(session, 7, chat_id=-100123)
    assert toggled is True
    assert rule.is_active is False

    deleted_ok = await auto_reply_service.delete_auto_reply_rule(session, 7, chat_id=-100123)
    assert deleted_ok is True
    assert deleted == [7]


@pytest.mark.asyncio
async def test_move_auto_reply_rule_swaps_sort_order(monkeypatch) -> None:
    session = _FakeSession()
    rules = [
        SimpleNamespace(id=1, sort_order=1),
        SimpleNamespace(id=2, sort_order=2),
        SimpleNamespace(id=3, sort_order=3),
    ]

    async def fake_get_chat_auto_reply_rules(session, chat_id: int, active_only: bool = False):
        return rules

    monkeypatch.setattr(auto_reply_service, "get_chat_auto_reply_rules", fake_get_chat_auto_reply_rules)

    moved = await auto_reply_service.move_auto_reply_rule(
        session,
        chat_id=-100123,
        rule_id=2,
        direction="up",
    )

    assert moved is True
    assert rules[0].sort_order == 2
    assert rules[1].sort_order == 1
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_auto_reply_delete_do_callback_answers_once(monkeypatch) -> None:
    session = _FakeSession()
    q = _FakeCallbackQuery("auto_reply:delete:-100456:9:do")
    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(id=-100456, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    async def fake_resolve_target_chat_id(update, context, chat_index: int = 2):
        return -100456

    render_calls = []

    async def fake_render(update, context, target_chat_id: int, page: int = 0):
        render_calls.append((target_chat_id, page))

    async def fake_delete_rule(session, rule_id: int, chat_id: int | None = None):
        assert rule_id == 9
        assert chat_id == -100456
        return True

    monkeypatch.setattr(auto_reply_handler, "_resolve_auto_reply_target_chat_id", fake_resolve_target_chat_id)
    monkeypatch.setattr(auto_reply_handler, "_render_auto_reply_list", fake_render)
    monkeypatch.setattr(auto_reply_handler, "delete_auto_reply_rule", fake_delete_rule)

    await auto_reply_handler.auto_reply_delete_do_callback(update, context)

    assert q.answers == [("规则已删除", False)]
    assert render_calls == [(-100456, 0)]


@pytest.mark.asyncio
async def test_auto_reply_edit_callback_passes_state_writer(monkeypatch) -> None:
    captured = {}

    async def fake_edit_action(update, context, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(auto_reply_handler, "auto_reply_edit_action", fake_edit_action)

    await auto_reply_handler.auto_reply_edit_callback(SimpleNamespace(), SimpleNamespace())

    assert captured["set_user_state_func"] is auto_reply_handler.set_user_state


def test_auto_reply_list_keyboard_contains_management_callbacks() -> None:
    rules = [
        SimpleNamespace(id=9, sort_order=2, is_active=True),
    ]

    keyboard = auto_reply_list_keyboard(rules, chat_id=-100456)

    row = keyboard.inline_keyboard[0]
    assert row[0].text == "顺序 2"
    assert row[0].callback_data == "auto_reply:detail:-100456:9"
    assert row[1].text == "✅ 启用"
    assert row[1].callback_data == "auto_reply:set:-100456:9:active:0"
    assert row[2].callback_data == "auto_reply:detail:-100456:9"
    assert row[3].callback_data == "auto_reply:delete:-100456:9:confirm"
    assert keyboard.inline_keyboard[1][0].text == "➕ 添加一条"


def test_auto_reply_detail_keyboard_contains_edit_callbacks() -> None:
    rule = SimpleNamespace(id=9)
    keyboard = auto_reply_detail_keyboard(rule, chat_id=-100456)

    assert keyboard.inline_keyboard[0][1].callback_data == "auto_reply:set:-100456:9:active:1"
    assert keyboard.inline_keyboard[0][2].text == "✅ 关闭"
    assert keyboard.inline_keyboard[1][1].text == "✅ 等于"
    assert keyboard.inline_keyboard[1][2].callback_data == "auto_reply:set:-100456:9:match:contains"
    assert keyboard.inline_keyboard[2][2].callback_data == "auto_reply:set:-100456:9:source:0"
    assert keyboard.inline_keyboard[3][0].callback_data == "auto_reply:edit:-100456:9:keywords"
    assert keyboard.inline_keyboard[3][1].callback_data == "auto_reply:edit:-100456:9:cover"
    assert keyboard.inline_keyboard[4][0].callback_data == "auto_reply:edit:-100456:9:content"
    assert keyboard.inline_keyboard[4][1].callback_data == "btned:open:auto_reply:-100456:9"
    assert keyboard.inline_keyboard[5][1].callback_data == "auto_reply:delay:-100456:9"


def test_auto_reply_menu_keyboard_uses_short_labels() -> None:
    keyboard = auto_reply_menu_keyboard(chat_id=-100456)

    assert keyboard.inline_keyboard[0][0].text == "➕ 添加一条"
    assert keyboard.inline_keyboard[1][0].text == "📋 规则列表"


def test_format_auto_reply_rule_detail_has_new_fields() -> None:
    rule = SimpleNamespace(
        id=7,
        sort_order=3,
        is_active=True,
        match_type="contains",
        case_sensitive=False,
        delete_source=True,
        delete_reply_delay_seconds=45,
        match_count=12,
        keywords=["hello", "world"],
        reply_content="test reply",
        cover_media_type="photo",
        cover_media_file_id="file123",
        buttons=[[{"text": "官网", "url": "https://example.com"}]],
        stop_after_match=False,
    )

    text = _format_auto_reply_rule_detail(rule)

    assert "💬 自动回复" in text
    assert "📸 关键词: 【hello、world】" in text
    assert "🏞️ 封面设置: 已设置" in text
    assert "📄 文本内容: test reply" in text
    assert "⭕ 设置按钮: 已设置 1 个" in text
    assert "⚙️ 状态: ✅ 启用" in text
    assert "🎯 匹配: 包含" in text
    assert "🧹 删除来源: 删除" in text
    assert "🕘 延迟删除: 45秒后删除" in text


def test_parse_auto_reply_buttons_input_accepts_line_format() -> None:
    buttons = _parse_auto_reply_buttons_input("官网|https://example.com\n帮助|https://help.example.com")

    assert buttons == [
        [{"text": "官网", "url": "https://example.com"}],
        [{"text": "帮助", "url": "https://help.example.com"}],
    ]


@pytest.mark.asyncio
async def test_send_auto_reply_payload_falls_back_to_text_when_cover_fails() -> None:
    bot = _FakeAutoReplyBot(fail_photo=True)
    context = SimpleNamespace(bot=bot)
    rule = SimpleNamespace(
        cover_media_type="photo",
        cover_media_file_id="bad-file-id",
        buttons=[],
    )

    sent = await send_auto_reply_payload(
        context,
        chat_id=-100123,
        text="123",
        rule=rule,
        reply_to_message_id=55,
    )

    assert sent.message_id == 101
    assert [name for name, _ in bot.calls] == ["send_photo", "send_message"]
    assert bot.calls[1][1] == {
        "chat_id": -100123,
        "text": "123",
        "reply_markup": None,
        "reply_to_message_id": 55,
        "allow_sending_without_reply": True,
    }


@pytest.mark.asyncio
async def test_send_auto_reply_payload_retries_text_without_broken_reply_reference() -> None:
    bot = _FakeAutoReplyBot(fail_message_with_reply=True)
    context = SimpleNamespace(bot=bot)
    rule = SimpleNamespace(
        cover_media_type=None,
        cover_media_file_id=None,
        buttons=[],
    )

    sent = await send_auto_reply_payload(
        context,
        chat_id=-100123,
        text="123",
        rule=rule,
        reply_to_message_id=55,
        message_thread_id=9,
    )

    assert sent.message_id == 101
    assert [name for name, _ in bot.calls] == ["send_message", "send_message"]
    assert bot.calls[0][1]["reply_to_message_id"] == 55
    assert bot.calls[0][1]["message_thread_id"] == 9
    assert bot.calls[1][1]["reply_to_message_id"] is None
    assert bot.calls[1][1]["message_thread_id"] == 9


def test_auto_reply_list_keyboard_adds_pagination_when_needed() -> None:
    rules = [
        SimpleNamespace(id=index, sort_order=index, is_active=True)
        for index in range(1, 10)
    ]

    keyboard = auto_reply_list_keyboard(
        rules,
        chat_id=-100456,
        page=0,
        page_size=8,
        total_count=len(rules),
    )

    assert keyboard.inline_keyboard[-3][0].text == "📄 1/2"
    assert keyboard.inline_keyboard[-3][1].callback_data == "auto_reply:list:-100456:1"


def test_auto_reply_delay_keyboard_marks_current_delay() -> None:
    rule = SimpleNamespace(id=9, delete_reply_delay_seconds=30)

    keyboard = auto_reply_delay_keyboard(rule, chat_id=-100456)

    assert keyboard.inline_keyboard[0][1].text == "✅ 30秒"
    assert keyboard.inline_keyboard[0][1].callback_data == "auto_reply:delay:set:-100456:9:30"
    assert keyboard.inline_keyboard[1][0].callback_data == "auto_reply:delay:set:-100456:9:0"


@pytest.mark.asyncio
async def test_create_auto_reply_draft_is_disabled_and_empty(monkeypatch) -> None:
    session = _FakeSession()

    async def fake_get_next_sort_order(session, chat_id: int) -> int:
        return 4

    monkeypatch.setattr(auto_reply_service, "get_next_sort_order", fake_get_next_sort_order)

    rule = await auto_reply_service.create_auto_reply_draft(
        session,
        chat_id=-100123,
        created_by_user_id=42,
    )

    assert rule.keywords == []
    assert rule.reply_content == ""
    assert rule.match_type == "exact"
    assert rule.delete_source is False
    assert rule.delete_reply_delay_seconds == 0
    assert rule.is_active is False
    assert rule.sort_order == 4
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_auto_reply_set_callback_rejects_incomplete_enable(monkeypatch) -> None:
    session = _FakeSession()
    q = _FakeCallbackQuery("auto_reply:set:-100456:9:active:1")
    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(id=10001, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    rule = SimpleNamespace(id=9, chat_id=-100456, keywords=[], reply_content="", is_active=False)

    async def fake_resolve_target_chat_id(update, context, chat_index: int = 2):
        return -100456

    async def fake_get_rule(session, chat_id: int, rule_id: int):
        return rule

    async def fake_update_rule(*args, **kwargs):
        raise AssertionError("incomplete rule should not be enabled")

    monkeypatch.setattr(auto_reply_handler, "_resolve_auto_reply_target_chat_id", fake_resolve_target_chat_id)
    monkeypatch.setattr(auto_reply_handler, "get_auto_reply_rule_in_chat", fake_get_rule)
    monkeypatch.setattr(auto_reply_handler, "update_auto_reply_rule", fake_update_rule)

    await auto_reply_handler.auto_reply_set_callback(update, context)

    assert q.answers == [("请先配置关键词", True)]


def test_extract_auto_reply_list_page_only_reads_real_list_callback() -> None:
    assert _extract_auto_reply_list_page("auto_reply:list:-100456:3") == 3
    assert _extract_auto_reply_list_page("auto_reply:move:-100456:9:up") == 0
    assert _extract_auto_reply_list_page("auto_reply:delete:-100456:9:do") == 0
    assert _extract_auto_reply_list_page(None) == 0


@pytest.mark.asyncio
async def test_match_auto_reply_continues_when_stop_after_match_disabled(monkeypatch) -> None:
    session = _FakeSession()
    updates: list[tuple[object, dict]] = []
    rules = [
        SimpleNamespace(
            id=1,
            match_type="contains",
            keywords=["hello"],
            case_sensitive=False,
            match_count=0,
            stop_after_match=False,
            reply_content="first",
        ),
        SimpleNamespace(
            id=2,
            match_type="contains",
            keywords=["world"],
            case_sensitive=False,
            match_count=3,
            stop_after_match=True,
            reply_content="second",
        ),
    ]

    async def fake_get_chat_auto_reply_rules(session, chat_id: int, active_only: bool = False):
        return rules

    async def fake_update_entity(session, entity, payload):
        updates.append((entity, payload))
        entity.match_count = payload["match_count"]

    monkeypatch.setattr(auto_reply_service, "get_chat_auto_reply_rules", fake_get_chat_auto_reply_rules)
    monkeypatch.setattr(auto_reply_service.ServiceBase, "_update_entity", fake_update_entity)

    result = await auto_reply_service.match_auto_reply(session, -100123, "hello world")

    assert result.success is True
    assert [rule.id for rule in result.matched_rules] == [1, 2]
    assert result.rule.id == 1
    assert result.reply_content == "first"
    assert [payload["match_count"] for _, payload in updates] == [1, 4]
