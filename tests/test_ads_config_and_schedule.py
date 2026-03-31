from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from bot.handlers.ads_handler import (
    _format_ad_detail_text,
    _parse_ad_id_from_callback,
    _parse_ads_config,
)
from bot.keyboards.content.ads import ads_menu_keyboard
from bot.services.automation.ad_service import get_ad_next_send_time, is_ad_exhausted, is_rotation_ad, should_send_ad


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
    # 2026-02-16 20:00 UTC+8 == 2026-02-16 12:00 UTC
    assert config["start_time"] == dt.datetime(2026, 2, 16, 12, 0, tzinfo=dt.UTC)
    assert config["content"] == "这是广告正文\n第二行"


def test_parse_ads_config_invalid_start_time_raises() -> None:
    text = """活动通知
开始时间: not-a-date
内容:
hello
"""
    with pytest.raises(ValueError):
        _parse_ads_config(text)


def test_parse_ad_id_from_callback_supports_colon_and_underscore() -> None:
    assert _parse_ad_id_from_callback("ads:send:123") == 123
    assert _parse_ad_id_from_callback("ads:delete_456") == 456
    assert _parse_ad_id_from_callback("ads:send:abc") == 0


def test_should_send_ad_new_interval_logic() -> None:
    now = dt.datetime.now(dt.UTC)
    ad = SimpleNamespace(
        enabled=True,
        interval_hours=24,
        start_time=None,
        schedule_time=None,
        created_at=now - dt.timedelta(hours=2),
        max_send_count=None,
        send_count=0,
        last_sent_at=None,
        frequency=None,
    )
    assert should_send_ad(ad) is True

    ad.last_sent_at = now - dt.timedelta(hours=23)
    assert should_send_ad(ad) is False

    ad.last_sent_at = now - dt.timedelta(hours=24, minutes=1)
    assert should_send_ad(ad) is True


def test_should_send_ad_legacy_once_logic() -> None:
    now = dt.datetime.now(dt.UTC)
    ad = SimpleNamespace(
        enabled=True,
        interval_hours=None,
        start_time=None,
        schedule_time=None,
        created_at=now,
        max_send_count=None,
        send_count=0,
        last_sent_at=None,
        frequency=None,
    )
    assert should_send_ad(ad) is True
    ad.last_sent_at = now
    assert should_send_ad(ad) is False


def test_format_ad_detail_text_contains_schedule_and_image() -> None:
    ad = SimpleNamespace(
        title="活动通知",
        content="正文内容",
        enabled=True,
        schedule_time=None,
        start_time=dt.datetime(2026, 2, 16, 12, 0, tzinfo=dt.UTC),
        interval_hours=24,
        max_send_count=7,
        send_count=2,
        frequency="daily",
        has_image=True,
        last_sent_at=dt.datetime(2026, 2, 16, 13, 0, tzinfo=dt.UTC),
    )

    text = _format_ad_detail_text(ad)

    assert "🟢 活动通知" in text
    assert "状态: 启用" in text
    assert "模式: 轮播" in text
    assert "🕒 开始: 2026-02-16 20:00 (UTC+8)" in text
    assert "🔁 间隔: 24小时" in text
    assert "📈 进度: 2/7" in text
    assert "⏭️ 下次: 2026-02-17 21:00 (UTC+8)" in text
    assert "🖼️ 含图片" in text
    assert "📤 上次发送: 2026-02-16 21:00 (UTC+8)" in text
    assert text.endswith("正文内容")


def test_get_ad_next_send_time_for_interval_and_exhausted() -> None:
    ad = SimpleNamespace(
        enabled=True,
        interval_hours=24,
        start_time=dt.datetime(2026, 2, 16, 12, 0, tzinfo=dt.UTC),
        schedule_time=None,
        created_at=dt.datetime(2026, 2, 16, 10, 0, tzinfo=dt.UTC),
        max_send_count=3,
        send_count=1,
        last_sent_at=dt.datetime(2026, 2, 17, 12, 0, tzinfo=dt.UTC),
        frequency=None,
    )

    assert is_rotation_ad(ad) is True
    assert is_ad_exhausted(ad) is False
    assert get_ad_next_send_time(ad) == dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC)

    ad.send_count = 3
    assert is_ad_exhausted(ad) is True
    assert get_ad_next_send_time(ad) is None


def test_ads_menu_keyboard_uses_rotation_labels() -> None:
    keyboard = ads_menu_keyboard(chat_id=-100123)

    assert keyboard.inline_keyboard[0][0].text == "➕ 创建轮播广告"
    assert keyboard.inline_keyboard[1][0].text == "📋 轮播列表"
    assert keyboard.inline_keyboard[1][1].text == "📊 轮播看板"
