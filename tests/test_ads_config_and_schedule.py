from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.features.automation.ads_handler import (
    _format_ad_detail_text,
    _parse_ad_id_from_callback,
    _parse_ads_config,
    _render_ads_home_text,
    ads_rules_callback,
)
from backend.features.automation.services.ad_rotation_service import (
    compute_next_run_at,
    describe_delete_policy,
    describe_rule_mode,
    format_interval_seconds_label,
    parse_interval_minutes_text,
    select_next_rotation_item,
)
from backend.features.automation.ui.ads import ads_copy_time_keyboard, ads_menu_keyboard, ads_rules_interval_keyboard, ads_rules_keyboard


def test_parse_ads_config_with_schedule_and_image_id() -> None:
    text = """活动通知

开始时间: 2026-02-16 20:00
推送间隔: 24小时
推送次数: 7次
图片ID: AgACAgUAAxkBAAIB...
内容:
这是广告正文
第二行
"""
    config = _parse_ads_config(text)

    assert config["title"] == "活动通知"
    assert config["interval_hours"] == 24
    assert config["max_send_count"] == 7
    assert config["image_file_id"] == "AgACAgUAAxkBAAIB..."
    assert config["start_time"] == dt.datetime(2026, 2, 16, 12, 0, tzinfo=dt.UTC)
    assert config["content"] == "这是广告正文\n第二行"


def test_parse_ad_id_from_callback_supports_new_and_legacy_formats() -> None:
    assert _parse_ad_id_from_callback("ads:item:preview:123") == 123
    assert _parse_ad_id_from_callback("ads:detail:456") == 456
    assert _parse_ad_id_from_callback("ads:delete_789") == 789
    assert _parse_ad_id_from_callback("ads:send:abc") == 0


def test_compute_next_run_at_prefers_future_start() -> None:
    now = dt.datetime(2026, 4, 14, 2, 0, tzinfo=dt.UTC)
    rule = SimpleNamespace(
        enabled=True,
        interval_seconds=7200,
        start_at=dt.datetime(2026, 4, 14, 4, 0, tzinfo=dt.UTC),
        last_sent_at=None,
    )

    assert compute_next_run_at(rule, now=now) == dt.datetime(2026, 4, 14, 4, 0, tzinfo=dt.UTC)


def test_select_next_rotation_item_respects_cursor_and_wrap() -> None:
    rule = SimpleNamespace(current_order_cursor=2)
    now = dt.datetime.now(dt.UTC)
    items = [
        SimpleNamespace(id=11, sort_order=1, enabled=True, start_time=None, end_time=None),
        SimpleNamespace(id=22, sort_order=2, enabled=True, start_time=None, end_time=None),
        SimpleNamespace(id=33, sort_order=3, enabled=True, start_time=None, end_time=None),
    ]

    item, next_cursor = select_next_rotation_item(rule, items, now=now)
    assert item.id == 22
    assert next_cursor == 3

    rule.current_order_cursor = 9
    item, next_cursor = select_next_rotation_item(rule, items, now=now)
    assert item.id == 11
    assert next_cursor == 2


def test_describe_rule_mode_and_delete_policy() -> None:
    rule = SimpleNamespace(mode="send_pin", delete_policy="delete_prev_cycle", delete_delay_seconds=60)
    assert describe_rule_mode(rule) == "轮流发送+置顶"
    assert describe_delete_policy(rule) == "删除上一轮相同消息"

    rule.delete_policy = "delete_delay"
    assert "60秒" in describe_delete_policy(rule)


def test_format_ad_detail_text_matches_detail_flow() -> None:
    ad = SimpleNamespace(
        title="优选榜单",
        content="郑州精品榜单",
        enabled=True,
        image_file_id="photo-file-id",
        buttons=[[{"text": "联系我", "url": "https://t.me/example"}]],
        start_time=dt.datetime(2026, 4, 14, 2, 0, tzinfo=dt.UTC),
        end_time=None,
    )

    text = _format_ad_detail_text(ad)

    assert "🎠 轮播消息" in text
    assert "📮 标题备注: 优选榜单" in text
    assert "🏞️ 封面设置: 已设置" in text
    assert "⭕ 设置按钮: 已设置 1 个" in text
    assert "📄 文本内容: 郑州精品榜单" in text
    assert "⚙️ 状态: ✅ 启用" in text


def test_render_ads_home_text_contains_rule_summary() -> None:
    rule = SimpleNamespace(
        enabled=True,
        start_at=dt.datetime(2026, 2, 28, 0, 0, tzinfo=dt.UTC),
        last_sent_at=dt.datetime(2026, 4, 14, 2, 0, tzinfo=dt.UTC),
        next_run_at=dt.datetime(2026, 4, 14, 4, 0, tzinfo=dt.UTC),
        interval_seconds=7200,
        mode="send",
        delete_policy="delete_prev_cycle",
        delete_delay_seconds=60,
        unpin_previous=True,
    )
    items = [SimpleNamespace(enabled=True, start_time=None, end_time=None)]

    text = _render_ads_home_text(rule, items)

    assert "轮播状态: ✅ 启用" in text
    assert "轮播间隔: 2小时" in text
    assert "删除上一轮相同消息" in text
    assert "当前生效的轮播条数: 1" in text


def test_ads_menu_keyboard_matches_screenshot_flow() -> None:
    keyboard = ads_menu_keyboard(chat_id=-100123)

    assert keyboard.inline_keyboard[0][0].text == "轮播规则设置"
    assert keyboard.inline_keyboard[0][1].text == "轮播广告管理"


def test_ads_rules_keyboard_shows_selected_options() -> None:
    rule = SimpleNamespace(
        enabled=True,
        mode="send",
        interval_seconds=7200,
        unpin_previous=True,
        delete_policy="delete_prev_cycle",
    )

    keyboard = ads_rules_keyboard(-100123, rule)

    assert keyboard.inline_keyboard[0][1].text == "✅ 启动"
    assert keyboard.inline_keyboard[1][1].text == "✅ 发送"
    assert keyboard.inline_keyboard[3][0].callback_data == "ads:rules:hint:-100123:unpin_previous"
    assert keyboard.inline_keyboard[6][2].text == "✅ 删上轮"


@pytest.mark.asyncio
async def test_ads_rules_hint_callback_tells_user_to_click_action_buttons() -> None:
    answered: list[tuple[str | None, bool | None]] = []

    async def fake_answer(text=None, show_alert=None):
        answered.append((text, show_alert))

    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            id="ads-rules-hint-test",
            data="ads:rules:hint:-100123:unpin_previous",
            answer=fake_answer,
        ),
    )
    context = SimpleNamespace()

    await ads_rules_callback(update, context)

    assert answered == [("这是说明栏，请点击下方「开启」或「关闭」按钮来切换取消上一条置顶。", False)]


def test_ads_rules_interval_keyboard_shows_minute_presets_and_current_value() -> None:
    keyboard = ads_rules_interval_keyboard(-100123, 7200)

    assert keyboard.inline_keyboard[0][0].text == "1分钟"
    assert keyboard.inline_keyboard[2][1].text == "✅ 2小时"
    assert keyboard.inline_keyboard[4][0].text == "自定义时间"


def test_parse_interval_minutes_text_supports_custom_minutes() -> None:
    assert parse_interval_minutes_text("90") == 5400
    assert parse_interval_minutes_text("2小时") == 7200
    assert parse_interval_minutes_text("1天") == 86400
    assert format_interval_seconds_label(1800) == "30分钟"


def test_ads_copy_time_keyboard_is_back_only_for_tg_time_prompt() -> None:
    keyboard = ads_copy_time_keyboard("ads:rules:-100123", "2026-04-14 12:00:00")

    button = keyboard.inline_keyboard[0][0]
    assert button.text == "🔙 返回"
    assert button.callback_data == "ads:rules:-100123"
    assert "copy_text" not in button.to_dict()


def test_ads_item_detail_keyboard_includes_chat_id_for_private_flow() -> None:
    from backend.features.automation.ui.ads import ads_item_detail_keyboard

    item = SimpleNamespace(id=99, enabled=True)
    keyboard = ads_item_detail_keyboard(-100123, item)

    assert keyboard.inline_keyboard[1][0].callback_data == "ads:item:input:-100123:99:title"
    assert keyboard.inline_keyboard[1][1].callback_data == "ads:item:input:-100123:99:cover"
    assert keyboard.inline_keyboard[2][1].callback_data == "btned:open:ads:-100123:99"


@pytest.mark.asyncio
async def test_ads_show_menu_uses_home_summary(monkeypatch) -> None:
    from backend.features.automation.ads_handler import AdsHandler

    handler = AdsHandler()
    rendered: list[tuple[str, object]] = []

    async def fake_safe_edit(update, text: str, reply_markup=None):
        rendered.append((text, reply_markup))

    async def fake_session_factory():
        return None

    class _SessionContext:
        async def __aenter__(self):
            return SimpleNamespace(commit=self._commit)

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def _commit(self):
            return None

    class _Db:
        def session_factory(self):
            return _SessionContext()

    async def fake_get_or_create_rotation_rule(session, chat_id):
        return SimpleNamespace(
            enabled=False,
            start_at=None,
            last_sent_at=None,
            next_run_at=None,
            interval_seconds=7200,
            mode="send",
            delete_policy="delete_prev_cycle",
            delete_delay_seconds=60,
            unpin_previous=True,
        )

    async def fake_list_rotation_items(session, chat_id):
        return []

    monkeypatch.setattr(handler.message_helper, "safe_edit", fake_safe_edit)
    monkeypatch.setattr("backend.features.automation.ads_handler.get_or_create_rotation_rule", fake_get_or_create_rotation_rule)
    monkeypatch.setattr("backend.features.automation.ads_handler.list_rotation_items", fake_list_rotation_items)

    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))
    await handler.show_menu(SimpleNamespace(), context, -100123)

    assert rendered
    assert "轮播状态:" in rendered[0][0]
