from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers.auto_reply_handler import _format_auto_reply_rule_detail, _parse_auto_reply_buttons_input
from bot.keyboards.content.auto_reply import auto_reply_detail_keyboard, auto_reply_list_keyboard, auto_reply_menu_keyboard
from bot.services.moderation import auto_reply_service


class _FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0

    def add(self, entity) -> None:
        self.added.append(entity)

    async def flush(self) -> None:
        self.flush_count += 1


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
    )

    assert result.success is True
    assert result.entity.sort_order == 5
    assert result.entity.delete_source is True
    assert result.entity.delete_reply_delay_seconds == 30
    assert result.entity.cover_media_type == "photo"
    assert result.entity.cover_media_file_id == "file-1"
    assert result.entity.buttons == [[{"text": "官网", "url": "https://example.com"}]]
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
    )

    text = _format_auto_reply_rule_detail(rule)

    assert "💬 自动回复规则 #3" in text
    assert "删除触发源: 删除" in text
    assert "回复延迟删除: 45 秒" in text
    assert "封面: 已设置（photo）" in text
    assert "按钮: 1 个" in text
    assert "关键词: hello, world" in text


def test_parse_auto_reply_buttons_input_accepts_line_format() -> None:
    buttons = _parse_auto_reply_buttons_input("官网|https://example.com\n帮助|https://help.example.com")

    assert buttons == [
        [{"text": "官网", "url": "https://example.com"}],
        [{"text": "帮助", "url": "https://help.example.com"}],
    ]
