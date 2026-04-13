from __future__ import annotations

import datetime as dt
import re

from backend.shared.services.base import ValidationError


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def parse_auction_end_at(raw: str, *, now: dt.datetime | None = None) -> dt.datetime:
    value = raw.strip()
    current = as_utc(now or now_utc())
    if re.fullmatch(r"\d+", value):
        minutes = int(value)
        if minutes <= 0:
            raise ValidationError("截止时间必须大于 0 分钟。")
        return current + dt.timedelta(minutes=minutes)

    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        hour, minute = map(int, value.split(":"))
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= current:
            target += dt.timedelta(days=1)
        return target

    raise ValidationError("截止时间格式错误，请输入分钟数或 HH:MM。")


def parse_bid_amount(raw: str) -> int | None:
    text = raw.strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    match = re.fullmatch(r"出价[:： ]*(\d+)", text)
    if match:
        return int(match.group(1))
    return None
