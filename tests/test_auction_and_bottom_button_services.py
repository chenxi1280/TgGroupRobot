from __future__ import annotations

import datetime as dt

import pytest

from bot.models.expansion import AuctionItem, BottomButtonLayout
from bot.services.activity.auction_service import format_auction_announcement, parse_auction_end_at, parse_bid_amount
from bot.services.base import ValidationError
from bot.services.integration.bottom_button_service import build_runtime_markup, sanitize_button_text


def test_parse_auction_end_at_supports_minutes():
    now = dt.datetime(2026, 3, 31, 12, 0, tzinfo=dt.UTC)
    assert parse_auction_end_at("30", now=now) == now + dt.timedelta(minutes=30)


def test_parse_auction_end_at_supports_hhmm_cross_day():
    now = dt.datetime(2026, 3, 31, 23, 30, tzinfo=dt.UTC)
    result = parse_auction_end_at("08:05", now=now)
    assert result == dt.datetime(2026, 4, 1, 8, 5, tzinfo=dt.UTC)


def test_parse_bid_amount_supports_plain_and_keyword():
    assert parse_bid_amount("188") == 188
    assert parse_bid_amount("出价 288") == 288
    assert parse_bid_amount("hello") is None


def test_format_auction_announcement_contains_icons():
    item = AuctionItem(
        id=1,
        chat_id=-1001,
        title="精品课程",
        start_price=100,
        current_price=188,
        status="running",
        end_at=dt.datetime(2026, 3, 31, 15, 0, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 3, 31, 14, 0, tzinfo=dt.UTC),
    )
    text = format_auction_announcement(item, bidder_name="用户 1")
    assert "💰 拍卖" in text
    assert "🟢 进行中" in text
    assert "当前领先" in text


def test_bottom_button_runtime_markup_supports_send_and_fill():
    layouts = [
        BottomButtonLayout(id=1, chat_id=-1001, row_no=1, col_no=1, button_text="发送", payload_text="你好", action_mode="send", sort_key=11),
        BottomButtonLayout(id=2, chat_id=-1001, row_no=1, col_no=2, button_text="填充", payload_text="关键词", action_mode="fill", sort_key=12),
    ]
    markup = build_runtime_markup(-1001, layouts)
    send_button = markup.inline_keyboard[0][0]
    fill_button = markup.inline_keyboard[0][1]
    assert send_button.callback_data == "btmrun:send:-1001:1"
    assert fill_button.switch_inline_query_current_chat == "关键词"


def test_sanitize_button_text_rejects_empty():
    with pytest.raises(ValidationError):
        sanitize_button_text("   ")
