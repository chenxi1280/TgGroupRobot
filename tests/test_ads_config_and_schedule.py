from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from bot.handlers.ads_handler import (
    _format_ad_detail_text,
    _parse_ad_id_from_callback,
    _parse_ads_config,
)
from bot.services.automation.ad_service import should_send_ad


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
        schedule_time=dt.datetime(2026, 2, 16, 12, 0, tzinfo=dt.UTC),
        frequency="daily",
        has_image=True,
        last_sent_at=dt.datetime(2026, 2, 16, 13, 0, tzinfo=dt.UTC),
    )

    text = _format_ad_detail_text(ad)

    assert "🟢 活动通知" in text
    assert "状态: 启用" in text
    assert "⏰ 定时: 2026-02-16 12:00 [每天]" in text
    assert "🖼️ 含图片" in text
    assert "📤 上次发送: 2026-02-16 13:00" in text
    assert text.endswith("正文内容")
