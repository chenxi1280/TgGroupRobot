from __future__ import annotations

import datetime as dt

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.db.schema.models.automation import AdCampaign, AdRotationRule
from backend.shared.services.base import ValidationError
from backend.shared.time_helper import LOCAL_TIMEZONE, parse_date_time_string
from backend.shared.ui.button_input import parse_button_rows

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1_440
SECONDS_PER_HOUR = SECONDS_PER_MINUTE * MINUTES_PER_HOUR
DEFAULT_ROTATION_INTERVAL_SECONDS = 2 * SECONDS_PER_HOUR
DEFAULT_DELETE_DELAY_SECONDS = 60
MIN_ROTATION_INTERVAL_SECONDS = 60

log = structlog.get_logger(__name__)


def format_local_datetime(value: dt.datetime | None, *, empty: str = "未设置") -> str:
    if value is None:
        return empty
    normalized = value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value
    return normalized.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime_text(value: str) -> dt.datetime | None:
    raw = (value or "").strip()
    if not raw or raw == "清空":
        return None
    timestamp = parse_date_time_string(raw)
    if timestamp is None:
        raise ValidationError("时间格式错误，请使用 YYYY-MM-DD HH:MM")
    return dt.datetime.fromtimestamp(timestamp, dt.UTC)


def _duration_minutes(raw: str) -> int:
    if raw.endswith("小时"):
        value, multiplier = raw.removesuffix("小时").strip(), MINUTES_PER_HOUR
    elif raw.endswith("天"):
        value, multiplier = raw.removesuffix("天").strip(), MINUTES_PER_DAY
    else:
        value, multiplier = raw, 1
    if not value.isdigit():
        raise ValidationError("请输入整数分钟，例如 90")
    return int(value) * multiplier


def parse_interval_minutes_text(value: str) -> int:
    raw = (value or "").strip().removesuffix("分钟").removesuffix("分").strip()
    seconds = _duration_minutes(raw) * SECONDS_PER_MINUTE
    if seconds < MIN_ROTATION_INTERVAL_SECONDS:
        raise ValidationError("轮播间隔不能小于 1 分钟")
    return seconds


def format_interval_seconds_label(interval_seconds: int | None) -> str:
    seconds = max(int(interval_seconds or DEFAULT_ROTATION_INTERVAL_SECONDS), MIN_ROTATION_INTERVAL_SECONDS)
    minutes = seconds // SECONDS_PER_MINUTE
    if minutes < MINUTES_PER_HOUR:
        return f"{minutes}分钟"
    if minutes == MINUTES_PER_HOUR:
        return "1小时"
    if minutes < MINUTES_PER_DAY:
        return f"{minutes // MINUTES_PER_HOUR}小时"
    if minutes == MINUTES_PER_DAY:
        return "1天"
    return f"{minutes // MINUTES_PER_DAY}天"


def parse_interval_hours_text(value: str) -> int:
    return parse_interval_minutes_text(value)


def parse_delay_seconds_text(value: str) -> int:
    raw = (value or "").strip().removesuffix("秒").strip()
    if not raw.isdigit():
        raise ValidationError("请输入整数秒数，例如 60")
    seconds = int(raw)
    if seconds <= 0:
        raise ValidationError("延迟删除秒数必须大于 0")
    return seconds


def parse_buttons_text(raw_text: str) -> list[list[dict[str, str]]]:
    return parse_button_rows(raw_text, allow_empty=False)


def _normalized_item_buttons(item: AdCampaign) -> list:
    buttons = getattr(item, "buttons", None) or []
    if not buttons:
        return []
    try:
        return ScheduledMessageService.normalize_buttons_config(buttons)
    except Exception as exc:
        log.warning("ad_rotation_buttons_normalize_failed", error=str(exc))
        return []


def _item_button_row(row: list[dict]) -> list[InlineKeyboardButton]:
    values = [
        (str(button.get("text") or "").strip(), str(button.get("url") or "").strip())
        for button in row
    ]
    return [InlineKeyboardButton(text, url=url) for text, url in values if text and url]


def build_item_markup(item: AdCampaign) -> InlineKeyboardMarkup | None:
    rows = [button_row for row in _normalized_item_buttons(item) if (button_row := _item_button_row(row))]
    return InlineKeyboardMarkup(rows) if rows else None


def get_effective_item_count(items: list[AdCampaign], now: dt.datetime | None = None) -> int:
    current = now or dt.datetime.now(dt.UTC)
    return sum(1 for item in items if is_rotation_item_effective(item, current))


def describe_rule_mode(rule: AdRotationRule) -> str:
    return "轮流发送+置顶" if rule.mode == "send_pin" else "轮流发送"


def describe_delete_policy(rule: AdRotationRule) -> str:
    if rule.delete_policy == "none":
        return "不删除"
    if rule.delete_policy == "delete_prev":
        return "删除上一条轮播"
    if rule.delete_policy == "delete_delay":
        delay = int(rule.delete_delay_seconds or DEFAULT_DELETE_DELAY_SECONDS)
        return f"延迟删除（{delay}秒）"
    return "删除上一轮相同消息"


def is_rotation_item_effective(item: AdCampaign, now: dt.datetime | None = None) -> bool:
    current = now or dt.datetime.now(dt.UTC)
    if not item.enabled:
        return False
    if item.start_time and item.start_time > current:
        return False
    if item.end_time and item.end_time <= current:
        return False
    return True


def compute_next_run_at(
    rule: AdRotationRule,
    *,
    now: dt.datetime | None = None,
    sent_at: dt.datetime | None = None,
) -> dt.datetime | None:
    if not rule.enabled:
        return None
    current = now or dt.datetime.now(dt.UTC)
    interval_seconds = max(int(rule.interval_seconds or DEFAULT_ROTATION_INTERVAL_SECONDS), MIN_ROTATION_INTERVAL_SECONDS)
    if sent_at is not None:
        return sent_at + dt.timedelta(seconds=interval_seconds)
    start_at = rule.start_at or current
    if start_at > current:
        return start_at
    if rule.last_sent_at:
        next_run = rule.last_sent_at + dt.timedelta(seconds=interval_seconds)
        return next_run if next_run > current else current
    return current
