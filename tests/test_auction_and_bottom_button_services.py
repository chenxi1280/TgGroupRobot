from __future__ import annotations

import datetime as dt

import pytest

from backend.platform.db.schema.models.expansion import AuctionItem, AuctionSetting, BottomButtonLayout
from backend.features.activity.services.auction_service import format_auction_announcement, parse_auction_end_at, parse_bid_amount
from backend.shared.services.base import ValidationError
from backend.features.group_ops.services import bottom_button_service
from backend.features.group_ops.services.bottom_button_service import build_runtime_markup, sanitize_button_text


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


def test_format_auction_final_announcement_guides_delivery():
    item = AuctionItem(
        id=1,
        chat_id=-1001,
        title="精品课程",
        start_price=100,
        current_price=188,
        status="ended",
        end_at=dt.datetime(2026, 3, 31, 15, 0, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 3, 31, 15, 0, tzinfo=dt.UTC),
    )

    text = format_auction_announcement(item, is_final=True, settlement_note="🏆 中标用户：42")

    assert "买卖双方按群内约定完成交付" in text
    assert "拍卖记录中复盘" not in text


def test_auction_setting_defaults_allow_group_members_to_create():
    assert AuctionSetting.__table__.c.create_permission.default.arg == "all"


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


@pytest.mark.asyncio
async def test_bottom_button_add_layout_button_targets_specific_empty_slot(monkeypatch):
    async def fake_list_layouts(session, chat_id: int):
        return [
            BottomButtonLayout(
                id=1,
                chat_id=chat_id,
                row_no=1,
                col_no=1,
                button_text="已有",
                payload_text="已有",
                action_mode="send",
                sort_key=11,
            )
        ]

    class _Session:
        def __init__(self):
            self.added: list[BottomButtonLayout] = []

        def add(self, layout):
            self.added.append(layout)

        async def flush(self):
            return None

    monkeypatch.setattr(bottom_button_service, "list_layouts", fake_list_layouts)
    session = _Session()

    layout = await bottom_button_service.add_layout_button(session, -1001, row_no=2, col_no=4)

    assert layout.row_no == 2
    assert layout.col_no == 4
    assert layout.sort_key == 24
    assert session.added == [layout]


@pytest.mark.asyncio
async def test_bottom_button_add_layout_button_rejects_occupied_position(monkeypatch):
    async def fake_list_layouts(session, chat_id: int):
        return [
            BottomButtonLayout(
                id=1,
                chat_id=chat_id,
                row_no=1,
                col_no=1,
                button_text="已有",
                payload_text="已有",
                action_mode="send",
                sort_key=11,
            )
        ]

    class _Session:
        def add(self, layout):
            raise AssertionError("occupied slots should not add a new layout")

    monkeypatch.setattr(bottom_button_service, "list_layouts", fake_list_layouts)

    with pytest.raises(ValidationError, match="该位置已经有按钮"):
        await bottom_button_service.add_layout_button(_Session(), -1001, row_no=1, col_no=1)


@pytest.mark.asyncio
async def test_bottom_button_delete_preserves_manual_layout_holes(monkeypatch):
    layout = BottomButtonLayout(
        id=3,
        chat_id=-1001,
        row_no=1,
        col_no=2,
        button_text="删除",
        payload_text="删除",
        action_mode="send",
        sort_key=12,
    )
    compact_called = False

    async def fake_get_layout(session, chat_id: int, layout_id: int):
        return layout

    async def fake_compact_layouts(session, chat_id: int):
        nonlocal compact_called
        compact_called = True

    class _Session:
        def __init__(self):
            self.deleted = None

        async def delete(self, item):
            self.deleted = item

        async def flush(self):
            return None

    monkeypatch.setattr(bottom_button_service, "get_layout", fake_get_layout)
    monkeypatch.setattr(bottom_button_service, "compact_layouts", fake_compact_layouts)
    session = _Session()

    await bottom_button_service.delete_layout_button(session, -1001, 3)

    assert session.deleted is layout
    assert compact_called is False
