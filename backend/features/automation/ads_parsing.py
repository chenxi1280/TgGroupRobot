from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class _AdsConfig:
    title: str
    schedule_time: dt.datetime | None = None
    start_time: dt.datetime | None = None
    interval_hours: int | None = None
    max_send_count: int | None = None
    image_file_id: str | None = None
    content: str = ""


def _match_prefixed_value(line: str, key: str) -> tuple[bool, str]:
    if not line.startswith(f"{key}:"):
        return False, ""
    return True, line.split(":", 1)[1].strip()


def _parse_start_time(time_str: str) -> dt.datetime | None:
    value = (time_str or "").strip()
    if not value:
        return None
    try:
        local_time = dt.datetime.strptime(value, "%Y-%m-%d %H:%M").replace(
            tzinfo=dt.timezone(dt.timedelta(hours=8))
        )
    except ValueError:
        return None
    return local_time.astimezone(dt.UTC)


def _parse_interval(interval_str: str) -> int | None:
    text = (interval_str or "").strip()
    match = re.match(r"^(\d+)\s*小时$", text)
    if not match:
        return None
    return int(match.group(1))


def _parse_send_count(count_str: str) -> int | None:
    text = (count_str or "").strip()
    match = re.match(r"^(\d+)\s*次$", text)
    if not match:
        return None
    return int(match.group(1))


def _required_parsed_value(line: str, key: str, parser, *, error: str):
    matched, value = _match_prefixed_value(line, key)
    if not matched:
        return False, None
    parsed = parser(value)
    if parsed is None:
        raise ValueError(error)
    return True, parsed


def _apply_ads_header_line(config: _AdsConfig, line: str) -> tuple[_AdsConfig, bool]:
    for key, field, parser, error in (
        ("开始时间", "start_time", _parse_start_time, "开始时间格式错误"),
        ("推送间隔", "interval_hours", _parse_interval, "推送间隔格式错误"),
        ("推送次数", "max_send_count", _parse_send_count, "推送次数格式错误"),
    ):
        matched, value = _required_parsed_value(line, key, parser, error=error)
        if matched:
            return replace(config, **{field: value}), False
    matched, value = _match_prefixed_value(line, "图片ID")
    if matched:
        return replace(config, image_file_id=value or None), False
    return config, line == "内容:"


def _parse_ads_config(text: str) -> dict:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    if not lines or not lines[0].strip():
        raise ValueError("广告标题不能为空")

    config = _AdsConfig(title=lines[0].strip())
    content_lines: list[str] = []
    in_content = False
    for raw_line in lines[1:]:
        if in_content:
            content_lines.append(raw_line)
            continue
        config, in_content = _apply_ads_header_line(config, raw_line.strip())
    content = "\n".join(content_lines).strip()
    if not content:
        raise ValueError("广告内容不能为空")
    return asdict(replace(config, content=content))
