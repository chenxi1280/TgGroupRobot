from __future__ import annotations

import datetime as dt
import re


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


def _parse_ads_config(text: str) -> dict:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    if not lines or not lines[0].strip():
        raise ValueError("广告标题不能为空")

    title = lines[0].strip()
    schedule_time = None
    start_time = None
    interval_hours = None
    max_send_count = None
    image_file_id = None
    content_lines: list[str] = []
    in_content = False

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not in_content:
            matched, value = _match_prefixed_value(line, "开始时间")
            if matched:
                start_time = _parse_start_time(value)
                if start_time is None:
                    raise ValueError("开始时间格式错误")
                continue

            matched, value = _match_prefixed_value(line, "推送间隔")
            if matched:
                interval_hours = _parse_interval(value)
                if interval_hours is None:
                    raise ValueError("推送间隔格式错误")
                continue

            matched, value = _match_prefixed_value(line, "推送次数")
            if matched:
                max_send_count = _parse_send_count(value)
                if max_send_count is None:
                    raise ValueError("推送次数格式错误")
                continue

            matched, value = _match_prefixed_value(line, "图片ID")
            if matched:
                image_file_id = value or None
                continue

            if line == "内容:":
                in_content = True
                continue
        else:
            content_lines.append(raw_line)

    content = "\n".join(content_lines).strip()
    if not content:
        raise ValueError("广告内容不能为空")

    return {
        "title": title,
        "schedule_time": schedule_time,
        "start_time": start_time,
        "interval_hours": interval_hours,
        "max_send_count": max_send_count,
        "image_file_id": image_file_id,
        "content": content,
    }
