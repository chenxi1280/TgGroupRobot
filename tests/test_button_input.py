from __future__ import annotations

import pytest

from backend.shared.services.base import ValidationError
from backend.shared.ui.button_input import is_clear_button_input, parse_button_rows
from backend.shared.ui.common.keyboard import back_button, confirm_delete_keyboard, pagination_row, toggle_row, url_button


def test_parse_button_rows_accepts_json_and_wraps_to_four_columns() -> None:
    buttons = parse_button_rows(
        '[['
        '{"text":"A","url":"https://a.com"},'
        '{"text":"B","url":"https://b.com"},'
        '{"text":"C","url":"https://c.com"},'
        '{"text":"D","url":"https://d.com"},'
        '{"text":"E","url":"https://e.com"}'
        ']]'
    )

    assert buttons == [
        [
            {"text": "A", "url": "https://a.com"},
            {"text": "B", "url": "https://b.com"},
            {"text": "C", "url": "https://c.com"},
            {"text": "D", "url": "https://d.com"},
        ],
        [{"text": "E", "url": "https://e.com"}],
    ]


def test_parse_button_rows_accepts_multiline_and_same_row_separators() -> None:
    buttons = parse_button_rows(
        "官网|example.com ; 帮助|https://help.example.com\n"
        "\n"
        "频道|@demo_channel；客服|t.me/support_bot"
    )

    assert buttons == [
        [
            {"text": "官网", "url": "https://example.com"},
            {"text": "帮助", "url": "https://help.example.com"},
        ],
        [
            {"text": "频道", "url": "https://t.me/demo_channel"},
            {"text": "客服", "url": "https://t.me/support_bot"},
        ],
    ]


@pytest.mark.parametrize("raw", ["/clear", "/clear@DemoBot", "清空"])
def test_parse_button_rows_accepts_all_clear_tokens(raw: str) -> None:
    assert is_clear_button_input(raw) is True
    assert parse_button_rows(raw) == []


def test_parse_button_rows_rejects_unsafe_urls() -> None:
    with pytest.raises(ValidationError, match="协议不安全"):
        parse_button_rows("坏按钮|javascript:alert(1)")


def test_parse_button_rows_rejects_empty_button_text() -> None:
    with pytest.raises(ValidationError, match="按钮文案和 URL 不能为空"):
        parse_button_rows("|https://example.com")


def test_parse_button_rows_empty_input_requires_explicit_allow_empty() -> None:
    with pytest.raises(ValidationError, match="按钮配置不能为空"):
        parse_button_rows("")

    assert parse_button_rows("", allow_empty=True) == []


def test_common_keyboard_helpers_preserve_callback_scope_and_normalize_url() -> None:
    assert back_button("sm:open:-100123:task1").callback_data == "sm:open:-100123:task1"
    assert url_button("频道", "@demo_channel").url == "https://t.me/demo_channel"

    row = pagination_row(
        page=1,
        total_pages=3,
        previous_callback="sm:list:-100123:0",
        next_callback="sm:list:-100123:2",
    )
    assert [button.callback_data for button in row] == ["sm:list:-100123:0", "_noop", "sm:list:-100123:2"]

    toggle = toggle_row(
        "状态：",
        enabled=True,
        on_callback="sm:set:-100123:task1:enabled:1",
        off_callback="sm:set:-100123:task1:enabled:0",
    )
    assert [button.callback_data for button in toggle] == ["_noop", "sm:set:-100123:task1:enabled:1", "sm:set:-100123:task1:enabled:0"]

    keyboard = confirm_delete_keyboard(
        confirm_callback="sm:del_do:-100123:task1",
        cancel_callback="sm:del_cancel:-100123:task1",
    )
    assert keyboard.inline_keyboard[0][0].callback_data == "sm:del_do:-100123:task1"
    assert keyboard.inline_keyboard[0][1].callback_data == "sm:del_cancel:-100123:task1"
