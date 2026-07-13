from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from backend.shared.services.base import ValidationError
from backend.shared.time_helper import LOCAL_TIMEZONE
_PARSE_OPTIONS_THRESHOLD_2 = 2



def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def parse_ratio(raw: str) -> str:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError("抽水比例格式错误，请输入 0 到 1 之间的小数，例如 0.1。")
    if value < 0 or value > 1:
        raise ValidationError("抽水比例必须在 0 到 1 之间。")
    return format(value.normalize(), "f")


def parse_deadline(raw: str, *, allow_iso: bool = True) -> dt.datetime:
    text = raw.strip()
    if allow_iso:
        try:
            target = dt.datetime.fromisoformat(text)
        except ValueError:
            pass
        else:
            if target.tzinfo is None:
                target = target.replace(tzinfo=LOCAL_TIMEZONE)
            target_utc = target.astimezone(dt.UTC)
            if target_utc <= now():
                raise ValidationError("截止时间必须晚于当前时间。")
            return target_utc

    try:
        target = dt.datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValidationError("截止时间格式错误，请使用 YYYY-MM-DD HH:MM。")
    target_utc = target.replace(tzinfo=LOCAL_TIMEZONE).astimezone(dt.UTC)
    if target_utc <= now():
        raise ValidationError("截止时间必须晚于当前时间。")
    return target_utc


def parse_options(raw: str) -> list[dict]:
    options: list[dict] = []
    for idx, line in enumerate([item.strip() for item in raw.splitlines() if item.strip()], start=1):
        if ":" in line:
            key, label = [part.strip() for part in line.split(":", 1)]
        else:
            key, label = str(idx), line
        if not key or not label:
            raise ValidationError("竞猜选项格式错误，请按 `编号:文案` 或每行一个文案输入。")
        options.append({"key": key[:16], "label": label[:32]})
    if len(options) < _PARSE_OPTIONS_THRESHOLD_2:
        raise ValidationError("至少需要 2 个竞猜选项。")
    return options
