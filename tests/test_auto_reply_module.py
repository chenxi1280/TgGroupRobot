from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.moderation import auto_reply_handler
from backend.features.moderation.auto_reply_handler import (
    _extract_auto_reply_list_page,
    _format_auto_reply_rule_detail,
    _parse_auto_reply_buttons_input,
)
from backend.features.moderation.ui.auto_reply import auto_reply_detail_keyboard, auto_reply_list_keyboard, auto_reply_menu_keyboard
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


def test_auto_reply_list_keyboard_contains_management_callbacks() -> None:
    rules = [
        SimpleNamespace(id=9, sort_order=2, is_active=True),
    ]

    keyboard = auto_reply_list_keyboard(rules, chat_id=-100456)

    assert keyboard.inline_keyboard[0][0].callback_data == "auto_reply:detail:-100456:9"
    assert keyboard.inline_keyboard[1][0].callback_data == "auto_reply:move:-100456:9:up"
    assert keyboard.inline_keyboard[1][2].callback_data == "auto_reply:preview:-100456:9"
    assert keyboard.inline_keyboard[1][3].callback_data == "auto_reply:toggle:-100456:9"
    assert keyboard.inline_keyboard[1][4].callback_data == "auto_reply:delete:-100456:9:confirm"


def test_auto_reply_detail_keyboard_contains_edit_callbacks() -> None:
    rule = SimpleNamespace(id=9)
    keyboard = auto_reply_detail_keyboard(rule, chat_id=-100456)

    assert keyboard.inline_keyboard[1][0].callback_data == "auto_reply:edit:-100456:9:keywords"
    assert keyboard.inline_keyboard[2][0].callback_data == "auto_reply:edit:-100456:9:cover"
    assert keyboard.inline_keyboard[3][0].callback_data == "auto_reply:cycle:-100456:9:match"
    assert keyboard.inline_keyboard[4][1].callback_data == "auto_reply:cycle:-100456:9:delay"
    assert keyboard.inline_keyboard[5][0].callback_data == "auto_reply:togglecfg:-100456:9:stop"


def test_auto_reply_menu_keyboard_uses_short_labels() -> None:
    keyboard = auto_reply_menu_keyboard(chat_id=-100456)

    assert keyboard.inline_keyboard[0][0].text == "➕ 创建自动回复"
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

    assert "💬 自动回复规则 #3" in text
    assert "删除触发源: 删除" in text
    assert "回复延迟删除: 45 秒" in text
    assert "命中后停止继续匹配: 否" in text
    assert "封面: 已设置（photo）" in text
    assert "按钮: 1 个" in text
    assert "关键词: hello, world" in text


def test_parse_auto_reply_buttons_input_accepts_line_format() -> None:
    buttons = _parse_auto_reply_buttons_input("官网|https://example.com\n帮助|https://help.example.com")

    assert buttons == [
        [{"text": "官网", "url": "https://example.com"}],
        [{"text": "帮助", "url": "https://help.example.com"}],
    ]


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

    assert keyboard.inline_keyboard[-2][0].text == "📄 1/2"
    assert keyboard.inline_keyboard[-2][1].callback_data == "auto_reply:list:-100456:1"


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
