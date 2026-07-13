from __future__ import annotations

import datetime as dt
import re
from enum import Enum
from typing import Any


def validate_positive_number(value: int, field_name: str = "数值") -> tuple[bool, str | None]:
    if value is None:
        return True, None
    if not isinstance(value, (int, float)):
        return False, f"{field_name}必须是数字"
    if value < 0:
        return False, f"{field_name}不能为负数"
    return True, None


def validate_future_time(time: dt.datetime, field_name: str = "时间") -> tuple[bool, str | None]:
    if time is None:
        return True, None
    now = dt.datetime.now(dt.timezone.utc)
    if time.tzinfo is None:
        return False, f"{field_name}必须包含时区信息"
    if time <= now:
        return False, f"{field_name}必须是未来时间"
    return True, None


def validate_string_length(
    text: str,
    min_length: int = 0,
    max_length: int = 1000,
    *, field_name: str = "文本",
) -> tuple[bool, str | None]:
    if text is None:
        return True, None
    length = len(text)
    if length < min_length:
        return False, f"{field_name}长度不能少于{min_length}个字符"
    if length > max_length:
        return False, f"{field_name}长度不能超过{max_length}个字符"
    return True, None


def validate_enum(
    value: str,
    enum_class: type[Enum],
    field_name: str = "字段",
) -> tuple[bool, str | None]:
    if value is None:
        return True, None
    valid_values = [e.value for e in enum_class]
    if value not in valid_values:
        return False, f"{field_name}必须是以下值之一: {', '.join(valid_values)}"
    return True, None


def validate_regex(
    pattern: str,
    field_name: str = "正则表达式",
) -> tuple[bool, str | None]:
    if pattern is None:
        return True, None
    try:
        re.compile(pattern)
        return True, None
    except re.error:
        return False, f"{field_name}不是有效的正则表达式"


def validate_required(
    value: Any,
    field_name: str = "字段",
) -> tuple[bool, str | None]:
    if value is None:
        return False, f"{field_name}不能为空"
    if isinstance(value, str) and not value.strip():
        return False, f"{field_name}不能为空"
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False, f"{field_name}不能为空"
    return True, None


def validate_range(
    value: int | float,
    min_value: int | float | None = None,
    max_value: int | float | None = None,
    *, field_name: str = "数值",
) -> tuple[bool, str | None]:
    if value is None:
        return True, None
    if min_value is not None and value < min_value:
        return False, f"{field_name}不能小于 {min_value}"
    if max_value is not None and value > max_value:
        return False, f"{field_name}不能大于 {max_value}"
    return True, None


def validate_url(
    url: str,
    field_name: str = "链接",
) -> tuple[bool, str | None]:
    if url is None:
        return True, None

    url_pattern = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$',
        re.IGNORECASE,
    )

    if not url_pattern.match(url):
        return False, f"{field_name}不是有效的URL"
    return True, None
