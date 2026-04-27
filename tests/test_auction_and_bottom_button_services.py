from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.features.group_ops import bottom_button_handler, text_trigger_runtime
from backend.features.admin.activity import bottom_button as bottom_button_admin
from backend.platform.db.schema.models.expansion import AuctionItem, AuctionSetting, BottomButtonLayout, BottomButtonSetting
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


def test_bottom_button_runtime_markup_uses_reply_keyboard():
    layouts = [
        BottomButtonLayout(id=1, chat_id=-1001, row_no=1, col_no=1, button_text="发送", payload_text="你好", action_mode="send", sort_key=11),
        BottomButtonLayout(id=2, chat_id=-1001, row_no=1, col_no=2, button_text="填充", payload_text="关键词", action_mode="fill", sort_key=12),
    ]
    markup = build_runtime_markup(-1001, layouts)
    assert markup.keyboard[0][0].text == "发送"
    assert markup.keyboard[0][1].text == "填充"
    assert markup.resize_keyboard is True
    assert markup.is_persistent is True


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
async def test_bottom_button_generate_syncs_reply_keyboard_without_leaving_message(monkeypatch):
    setting = BottomButtonSetting(
        chat_id=-1001,
        enabled=True,
        header_text="底部键盘已更新",
        generated_message_id=88,
        repeat_generate_enabled=True,
    )
    layout = BottomButtonLayout(
        id=1,
        chat_id=-1001,
        row_no=1,
        col_no=1,
        button_text="老师搜索",
        payload_text="老师搜索",
        action_mode="send",
        sort_key=11,
    )
    calls: list[tuple[str, int | None]] = []

    async def fake_get_or_create_setting(session, chat_id: int):
        return setting

    async def fake_list_layouts(session, chat_id: int):
        return [layout]

    class _Bot:
        async def delete_message(self, *, chat_id: int, message_id: int):
            calls.append(("delete", message_id))

        async def send_message(self, *, chat_id: int, text: str, reply_markup):
            calls.append(("send", None))
            assert text == "底部键盘已更新"
            assert reply_markup.keyboard[0][0].text == "老师搜索"
            return SimpleNamespace(message_id=99)

    class _Session:
        async def flush(self):
            calls.append(("flush", None))

    monkeypatch.setattr(bottom_button_service, "get_or_create_setting", fake_get_or_create_setting)
    monkeypatch.setattr(bottom_button_service, "list_layouts", fake_list_layouts)

    await bottom_button_service.generate_buttons(SimpleNamespace(bot=_Bot()), _Session(), -1001)

    assert calls == [("delete", 88), ("send", None), ("delete", 99), ("flush", None)]
    assert setting.generated_message_id is None
    assert setting.repeat_generate_enabled is False


@pytest.mark.asyncio
async def test_bottom_button_repeat_generation_is_disabled():
    assert await bottom_button_service.list_due_repeat_generate(object()) == []


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


@pytest.mark.asyncio
async def test_bottom_button_send_mode_runs_text_trigger_as_clicking_user(monkeypatch):
    layout = BottomButtonLayout(
        id=7,
        chat_id=-1001,
        row_no=1,
        col_no=1,
        button_text="签到",
        payload_text="签到",
        action_mode="send",
        sort_key=11,
    )
    captured: dict[str, object] = {}

    class _Session:
        async def commit(self):
            return None

    class _SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get_layout(session, chat_id: int, layout_id: int):
        captured["layout_lookup"] = (chat_id, layout_id)
        return layout

    async def fake_text_trigger(update, context, chat_id: int, payload: str):
        captured["trigger"] = (chat_id, payload, update.effective_user.id)
        return True

    async def forbidden_send_message(*args, **kwargs):
        raise AssertionError("handled bottom button triggers should not send bot text")

    class _Query:
        id = "bottom-button-sign"
        data = "btmrun:send:-1001:7"

        async def answer(self, **kwargs):
            captured["answer"] = kwargs

    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(message_id=99),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}),
        bot=SimpleNamespace(send_message=forbidden_send_message),
    )
    monkeypatch.setattr(bottom_button_handler, "get_layout", fake_get_layout)
    monkeypatch.setattr(bottom_button_handler, "try_group_text_trigger", fake_text_trigger)

    await bottom_button_handler.bottom_button_runtime_callback(update, context)

    assert captured["layout_lookup"] == (-1001, 7)
    assert captured["trigger"] == (-1001, "签到", 42)
    assert captured["answer"]["text"] == "已触发：签到"


@pytest.mark.asyncio
async def test_group_text_trigger_falls_back_to_teacher_search(monkeypatch):
    calls: list[tuple[str, int, str]] = []

    async def fake_points_trigger(update, context, payload: str):
        calls.append(("points", update.effective_user.id, payload))
        return False

    async def fake_teacher_trigger(update, context, chat_id: int, payload: str):
        calls.append(("teacher", chat_id, payload))
        return True

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    monkeypatch.setattr(text_trigger_runtime, "_try_points_text_trigger", fake_points_trigger)
    monkeypatch.setattr(text_trigger_runtime, "_try_teacher_search_trigger", fake_teacher_trigger)

    handled = await text_trigger_runtime.try_group_text_trigger(update, SimpleNamespace(), -1001, "附近")

    assert handled is True
    assert calls == [("points", 42, "附近"), ("teacher", -1001, "附近")]


@pytest.mark.asyncio
async def test_bottom_button_enable_generates_runtime_message_immediately(monkeypatch):
    calls: list[tuple[str, int, object]] = []

    class _Session:
        async def commit(self):
            calls.append(("commit", 0, self))

    class _SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            self.session = _Session()
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Controller(bottom_button_admin.BottomButtonAdminControllerMixin):
        async def _show_bottom_button_menu(self, update, context, chat_id: int):
            calls.append(("menu", chat_id, None))

    async def fake_update_setting(session, chat_id: int, **updates):
        calls.append(("setting", chat_id, updates))

    async def fake_generate(context, session, chat_id: int):
        calls.append(("generate", chat_id, session))

    monkeypatch.setattr(bottom_button_admin, "update_bottom_button_setting", fake_update_setting)
    monkeypatch.setattr(bottom_button_admin, "generate_bottom_buttons", fake_generate)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        callback_query=SimpleNamespace(data="btm:toggle:-1001:1"),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}))

    await _Controller()._handle_bottom_button(
        update,
        context,
        -1001,
        bottom_button_admin.CallbackParser.parse("btm:toggle:-1001:1"),
    )

    assert calls[0] == ("setting", -1001, {"enabled": True})
    assert calls[1][0:2] == ("generate", -1001)
    assert calls[2][0] == "commit"
    assert calls[3] == ("menu", -1001, None)


@pytest.mark.asyncio
async def test_bottom_button_disable_does_not_generate_runtime_message(monkeypatch):
    calls: list[str] = []

    class _Session:
        async def commit(self):
            calls.append("commit")

    class _SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Controller(bottom_button_admin.BottomButtonAdminControllerMixin):
        async def _show_bottom_button_menu(self, update, context, chat_id: int):
            calls.append("menu")

    async def fake_update_setting(session, chat_id: int, **updates):
        assert updates == {"enabled": False}
        calls.append("setting")

    async def forbidden_generate(*args, **kwargs):
        raise AssertionError("disabling bottom buttons should not generate a group message")

    monkeypatch.setattr(bottom_button_admin, "update_bottom_button_setting", fake_update_setting)
    monkeypatch.setattr(bottom_button_admin, "generate_bottom_buttons", forbidden_generate)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        callback_query=SimpleNamespace(data="btm:toggle:-1001:0"),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}))

    await _Controller()._handle_bottom_button(
        update,
        context,
        -1001,
        bottom_button_admin.CallbackParser.parse("btm:toggle:-1001:0"),
    )

    assert calls == ["setting", "commit", "menu"]


@pytest.mark.asyncio
async def test_reserved_group_text_commands_include_configured_points_aliases(monkeypatch):
    async def fake_get_chat_settings(session, chat_id: int):
        assert chat_id == -1001
        return SimpleNamespace(points_alias="查分", points_rank_alias="排行榜")

    monkeypatch.setattr("backend.shared.services.chat_service.get_chat_settings", fake_get_chat_settings)

    assert await text_trigger_runtime.is_reserved_group_text_command_for_chat(object(), -1001, "查分") is True
    assert await text_trigger_runtime.is_reserved_group_text_command_for_chat(object(), -1001, "排行榜") is True
    assert await text_trigger_runtime.is_reserved_group_text_command_for_chat(object(), -1001, "签到") is True
    assert await text_trigger_runtime.is_reserved_group_text_command_for_chat(object(), -1001, "普通口令") is False
