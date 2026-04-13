from __future__ import annotations

import re


def is_valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", (value or "").strip()))


def format_duration_label(seconds: int) -> str:
    safe_seconds = max(int(seconds or 0), 0)
    minutes = (safe_seconds + 59) // 60
    hours, rem = divmod(minutes, 60)
    if hours:
        if rem:
            return f"{hours}小时{rem}分钟"
        return f"{hours}小时"
    return f"{minutes}分钟"
