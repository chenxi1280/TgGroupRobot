# Scheduled Window Starvation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every scheduled-message occurrence is mapped to a valid UTC+8 business window without the current 30-day starvation behavior.

**Architecture:** Keep time calculation pure and independent of Telegram or database code. Compute the next candidate from the repeat interval, then clamp an out-of-window candidate directly to the next window opening instead of repeatedly adding an interval that may never intersect the window.

**Tech Stack:** Python 3.11, `datetime`, pytest

---

### Task 1: Align the PRD scheduling policy

**Files:**
- Modify: `docs/product/TgGroupRobot_PRD.md:4296-4310`

- [x] **Step 1: Add the explicit window policy**

Add this rule below the scheduled-message flow:

```markdown
定时窗口规则：

- 业务时区固定为 UTC+8。
- 按重复周期得到的候选时间位于允许窗口内时，直接使用候选时间。
- 候选时间位于窗口外时，顺延到下一个窗口的开始时刻，而不是继续累加重复周期。
- 跨日窗口内的候选时间保持不变；窗口外候选时间顺延到当天或次日的窗口开始时刻。
```

- [x] **Step 2: Verify the PRD wording**

Run:

```bash
rg -n "定时窗口规则|顺延到下一个窗口的开始时刻|跨日窗口" docs/product/TgGroupRobot_PRD.md
```

Expected: all three phrases are present in section 23.7.

### Task 2: Add failing regression tests

**Files:**
- Modify: `tests/test_time_helper_schedule.py`

- [x] **Step 1: Extend the time-helper imports**

Replace the existing import from `backend.shared.time_helper` with:

```python
from backend.shared.time_helper import (
    LOCAL_TIMEZONE,
    calculate_next_run_time,
    find_next_valid_time,
    format_timestamp,
    is_time_in_window,
    parse_date_time_string,
)
```

- [x] **Step 2: Add a UTC+8 timestamp helper and starvation tests**

Add:

```python
def _local_timestamp(year: int, month: int, day: int, hour: int) -> int:
    value = dt.datetime(year, month, day, hour, tzinfo=LOCAL_TIMEZONE)
    return int(value.timestamp())


def test_find_next_valid_time_clamps_daily_candidate_to_next_window_start() -> None:
    task = SimpleNamespace(repeat_interval_min=1440, day_start_hour=9, day_end_hour=18)
    candidate = _local_timestamp(2026, 7, 13, 19)

    result = find_next_valid_time(candidate, task)

    assert result == _local_timestamp(2026, 7, 14, 9)
    assert is_time_in_window(result, 9, 18)


def test_find_next_valid_time_clamps_twelve_hour_candidate() -> None:
    task = SimpleNamespace(repeat_interval_min=720, day_start_hour=9, day_end_hour=18)
    candidate = _local_timestamp(2026, 7, 13, 19)

    assert find_next_valid_time(candidate, task) == _local_timestamp(2026, 7, 14, 9)


def test_find_next_valid_time_uses_same_day_opening_before_window() -> None:
    task = SimpleNamespace(repeat_interval_min=1440, day_start_hour=9, day_end_hour=18)
    candidate = _local_timestamp(2026, 7, 13, 7)

    assert find_next_valid_time(candidate, task) == _local_timestamp(2026, 7, 13, 9)


def test_find_next_valid_time_clamps_cross_midnight_gap() -> None:
    task = SimpleNamespace(repeat_interval_min=1440, day_start_hour=22, day_end_hour=6)
    candidate = _local_timestamp(2026, 7, 13, 12)

    assert find_next_valid_time(candidate, task) == _local_timestamp(2026, 7, 13, 22)


def test_find_next_valid_time_preserves_valid_cross_midnight_candidate() -> None:
    task = SimpleNamespace(repeat_interval_min=1440, day_start_hour=22, day_end_hour=6)
    candidate = _local_timestamp(2026, 7, 14, 2)

    assert find_next_valid_time(candidate, task) == candidate
```

- [x] **Step 3: Run the new tests and verify RED**

Run:

```bash
python3 -c 'import subprocess,sys; command=[".venv/bin/python","-m","pytest","-q","tests/test_time_helper_schedule.py"]; result=subprocess.run(command,timeout=60); sys.exit(result.returncode)'
```

Expected: the daily, twelve-hour, same-day-opening and cross-midnight-gap tests fail because the current implementation returns an interval-stepped timestamp rather than the next opening.

### Task 3: Implement direct window-boundary calculation

**Files:**
- Modify: `backend/shared/time_helper.py:74-97`
- Test: `tests/test_time_helper_schedule.py`

- [x] **Step 1: Add a pure local-time helper**

Add below `calculate_next_run_time`:

```python
def _next_window_opening(
    local_candidate: dt.datetime,
    *,
    start_hour: int,
    end_hour: int,
) -> dt.datetime:
    opening = local_candidate.replace(
        hour=start_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    if start_hour <= end_hour and local_candidate.hour < start_hour:
        return opening
    if start_hour > end_hour and end_hour < local_candidate.hour < start_hour:
        return opening
    return opening + dt.timedelta(days=1)
```

- [x] **Step 2: Replace interval stepping**

Replace `find_next_valid_time` with:

```python
def find_next_valid_time(from_timestamp: int, task: ScheduledMessageTask) -> int:
    """Return the candidate or the next UTC+8 window opening."""
    if is_time_in_window(from_timestamp, task.day_start_hour, task.day_end_hour):
        return from_timestamp

    local_candidate = dt.datetime.fromtimestamp(
        from_timestamp,
        dt.UTC,
    ).astimezone(LOCAL_TIMEZONE)
    next_opening = _next_window_opening(
        local_candidate,
        start_hour=task.day_start_hour,
        end_hour=task.day_end_hour,
    )
    return int(next_opening.astimezone(dt.UTC).timestamp())
```

- [x] **Step 3: Run focused tests and verify GREEN**

Run:

```bash
python3 -c 'import subprocess,sys; command=[".venv/bin/python","-m","pytest","-q","tests/test_time_helper_schedule.py","tests/test_scheduled_message_scheduler.py"]; result=subprocess.run(command,timeout=60); sys.exit(result.returncode)'
```

Expected: both modules pass with no new warning.

- [x] **Step 4: Run the original concrete reproducer**

Run:

```bash
.venv/bin/python -c 'import datetime as dt; from types import SimpleNamespace; from backend.shared.time_helper import LOCAL_TIMEZONE,find_next_valid_time,is_time_in_window; start=int(dt.datetime(2026,7,13,19,tzinfo=LOCAL_TIMEZONE).timestamp()); task=SimpleNamespace(repeat_interval_min=1440,day_start_hour=9,day_end_hour=18); result=find_next_valid_time(start,task); print(dt.datetime.fromtimestamp(result,dt.UTC).astimezone(LOCAL_TIMEZONE).isoformat(),is_time_in_window(result,9,18))'
```

Expected: `2026-07-14T09:00:00+08:00 True`.

### Task 4: Verify and commit the closed batch

**Files:**
- Modify: `backend/shared/time_helper.py`
- Modify: `tests/test_time_helper_schedule.py`
- Modify: `docs/product/TgGroupRobot_PRD.md`

- [x] **Step 1: Run the full test suite**

Run:

```bash
python3 -c 'import subprocess,sys; command=[".venv/bin/python","-m","pytest","-q"]; result=subprocess.run(command,timeout=60); sys.exit(result.returncode)'
```

Expected: all tests pass; the existing PTB warnings are handled in the later conversation-state batch.

- [x] **Step 2: Run syntax and whitespace checks**

Run:

```bash
.venv/bin/python -m compileall -q backend tests main.py
git diff --check
```

Expected: both commands exit 0.

- [x] **Step 3: Commit only this batch**

Run:

```bash
git add backend/shared/time_helper.py tests/test_time_helper_schedule.py docs/product/TgGroupRobot_PRD.md docs/superpowers/plans/2026-07-13-scheduled-window-starvation.md
git commit -m "Fix scheduled message window starvation"
```

Expected: one commit containing policy, tests, implementation and plan; unrelated user changes remain unstaged.
