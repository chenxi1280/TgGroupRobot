from __future__ import annotations

import datetime as dt
import re

from backend.shared.services.base import ValidationError
from backend.shared.time_helper import LOCAL_TIMEZONE


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def parse_auction_end_at(raw: str, *, now: dt.datetime | None = None) -> dt.datetime:
    value = raw.strip()
    current = as_utc(now or now_utc())
    try:
        target = dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValidationError("截止时间格式错误，请使用 YYYY-MM-DD HH:MM。")
    target_utc = target.replace(tzinfo=LOCAL_TIMEZONE).astimezone(dt.UTC)
    if target_utc <= current:
        raise ValidationError("截止时间必须晚于当前时间。")
    return target_utc


def parse_bid_amount(raw: str) -> int | None:
    text = raw.strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    match = re.fullmatch(r"出价[:： ]*(\d+)", text)
    if match:
        return int(match.group(1))
    return None
