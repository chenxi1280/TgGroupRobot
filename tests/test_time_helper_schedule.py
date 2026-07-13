from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from backend.shared.time_helper import (
    LOCAL_TIMEZONE,
    calculate_next_run_time,
    find_next_valid_time,
    format_timestamp,
    is_time_in_window,
    parse_date_time_string,
)


def _local_timestamp(year: int, month: int, day: int, hour: int) -> int:
    value = dt.datetime(year, month, day, hour, tzinfo=LOCAL_TIMEZONE)
    return int(value.timestamp())


def test_parse_date_time_string_uses_local_timezone_utc8() -> None:
    # 2026-01-01 08:00 (UTC+8) => 2026-01-01 00:00 (UTC)
    ts = parse_date_time_string("2026-01-01 08:00")
    assert ts == int(dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.UTC).timestamp())


def test_format_timestamp_outputs_local_timezone_utc8() -> None:
    ts = int(dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.UTC).timestamp())
    assert format_timestamp(ts) == "2026-01-01 08:00"


def test_is_time_in_window_all_day() -> None:
    local_tz = dt.timezone(dt.timedelta(hours=8))
    ts = int(dt.datetime(2026, 1, 1, 23, 30, tzinfo=local_tz).timestamp())
    assert is_time_in_window(ts, 0, 23) is True


def test_calculate_next_run_time_first_run_immediate() -> None:
    task = SimpleNamespace(
        start_at=None,
        repeat_interval_min=60,
        day_start_hour=0,
        day_end_hour=23,
    )
    now = int(dt.datetime.now(dt.UTC).timestamp())
    next_run = calculate_next_run_time(task)
    assert next_run <= now + 2


def test_calculate_next_run_time_respects_future_start() -> None:
    now = int(dt.datetime.now(dt.UTC).timestamp())
    task = SimpleNamespace(
        start_at=now + 3600,
        repeat_interval_min=60,
        day_start_hour=0,
        day_end_hour=23,
    )
    assert calculate_next_run_time(task) == task.start_at


def test_find_next_valid_time_clamps_daily_candidate_to_next_window_start() -> None:
    task = SimpleNamespace(
        repeat_interval_min=1440,
        day_start_hour=9,
        day_end_hour=18,
    )
    candidate = _local_timestamp(2026, 7, 13, 19)

    result = find_next_valid_time(candidate, task)

    assert result == _local_timestamp(2026, 7, 14, 9)
    assert is_time_in_window(result, 9, 18)


def test_find_next_valid_time_clamps_twelve_hour_candidate() -> None:
    task = SimpleNamespace(
        repeat_interval_min=720,
        day_start_hour=9,
        day_end_hour=18,
    )
    candidate = _local_timestamp(2026, 7, 13, 19)

    assert find_next_valid_time(candidate, task) == _local_timestamp(2026, 7, 14, 9)


def test_find_next_valid_time_uses_same_day_opening_before_window() -> None:
    task = SimpleNamespace(
        repeat_interval_min=1440,
        day_start_hour=9,
        day_end_hour=18,
    )
    candidate = _local_timestamp(2026, 7, 13, 7)

    assert find_next_valid_time(candidate, task) == _local_timestamp(2026, 7, 13, 9)


def test_find_next_valid_time_clamps_cross_midnight_gap() -> None:
    task = SimpleNamespace(
        repeat_interval_min=1440,
        day_start_hour=22,
        day_end_hour=6,
    )
    candidate = _local_timestamp(2026, 7, 13, 12)

    assert find_next_valid_time(candidate, task) == _local_timestamp(2026, 7, 13, 22)


def test_find_next_valid_time_preserves_valid_cross_midnight_candidate() -> None:
    task = SimpleNamespace(
        repeat_interval_min=1440,
        day_start_hour=22,
        day_end_hour=6,
    )
    candidate = _local_timestamp(2026, 7, 14, 2)

    assert find_next_valid_time(candidate, task) == candidate
