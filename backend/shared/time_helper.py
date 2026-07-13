from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
_GET_INTERVAL_DESCRIPTION_THRESHOLD_1440 = 1440
_GET_INTERVAL_DESCRIPTION_THRESHOLD_60 = 60
_IS_TIME_IN_WINDOW_THRESHOLD_23 = 23


if TYPE_CHECKING:
    from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask

LOCAL_TIMEZONE = dt.timezone(dt.timedelta(hours=8))


def is_time_in_window(timestamp: int, day_start_hour: int, day_end_hour: int) -> bool:
    """
    检查时间是否在时段窗口内

    Args:
        timestamp: Unix 时间戳
        day_start_hour: 每日开始小时（0-23）
        day_end_hour: 每日结束小时（0-23）

    Returns:
        True 如果时间在窗口内，否则返回 False
    """
    # 使用业务本地时区（UTC+8）计算小时，和界面配置保持一致
    local_time = dt.datetime.fromtimestamp(timestamp, dt.UTC).astimezone(LOCAL_TIMEZONE)
    current_hour = local_time.hour

    # 0-23 在界面中表示全天
    if day_start_hour == 0 and day_end_hour == _IS_TIME_IN_WINDOW_THRESHOLD_23:
        return True

    # 处理跨天时段
    if day_start_hour <= day_end_hour:
        # 正常时段：如 9-18（含边界）
        return day_start_hour <= current_hour <= day_end_hour
    else:
        # 跨天时段：如 22-6（22:00 到次日 06:00）
        return current_hour >= day_start_hour or current_hour <= day_end_hour


def calculate_next_run_time(task: ScheduledMessageTask, last_sent_timestamp: int | None = None) -> int:
    """
    计算下次运行时间

    Args:
        task: 定时消息任务
        last_sent_timestamp: 上次发送时间戳（可选）

    Returns:
        下次运行的 Unix 时间戳
    """
    now = int(dt.datetime.now(dt.UTC).timestamp())

    interval_seconds = task.repeat_interval_min * 60

    # 首次调度：start_at 为空时立即可运行；有 start_at 时按 start_at 开始
    if last_sent_timestamp is None:
        next_time = task.start_at if task.start_at is not None else now
        if next_time < now and task.start_at is not None:
            next_time = now
    else:
        # 已发送过：按固定间隔滚动
        next_time = last_sent_timestamp + interval_seconds
        while next_time < now:
            next_time += interval_seconds

    # 考虑时段窗口，找到下一个有效时间点
    if not is_time_in_window(next_time, task.day_start_hour, task.day_end_hour):
        next_time = find_next_valid_time(next_time, task)

    return next_time


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


def find_next_valid_time(from_timestamp: int, task: ScheduledMessageTask) -> int:
    """返回候选时间或下一个 UTC+8 业务窗口的开始时刻。"""
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


def datetime_to_timestamp(dt_obj: dt.datetime) -> int:
    """
    将 datetime 对象转换为 Unix 时间戳

    Args:
        dt_obj: datetime 对象

    Returns:
        Unix 时间戳
    """
    return int(dt_obj.timestamp())


def timestamp_to_datetime(timestamp: int) -> dt.datetime:
    """
    将 Unix 时间戳转换为 datetime 对象

    Args:
        timestamp: Unix 时间戳

    Returns:
        datetime 对象（UTC）
    """
    return dt.datetime.fromtimestamp(timestamp, dt.UTC)


def parse_date_time_string(date_str: str) -> int | None:
    """
    解析日期时间字符串为 Unix 时间戳

    Args:
        date_str: 日期时间字符串，格式：YYYY-MM-DD HH:MM

    Returns:
        Unix 时间戳，解析失败返回 None
    """
    try:
        local_dt = dt.datetime.strptime(date_str, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TIMEZONE)
        return int(local_dt.astimezone(dt.UTC).timestamp())
    except (ValueError, TypeError):
        return None


def format_timestamp(timestamp: int, format_str: str = "%Y-%m-%d %H:%M") -> str:
    """
    格式化时间戳为字符串

    Args:
        timestamp: Unix 时间戳
        format_str: 格式字符串

    Returns:
        格式化后的时间字符串
    """
    dt_obj = dt.datetime.fromtimestamp(timestamp, dt.UTC).astimezone(LOCAL_TIMEZONE)
    return dt_obj.strftime(format_str)


def get_interval_description(minutes: int) -> str:
    """
    获取间隔时间的友好描述

    Args:
        minutes: 间隔分钟数

    Returns:
        友好的时间描述
    """
    if minutes < _GET_INTERVAL_DESCRIPTION_THRESHOLD_60:
        return f"每 {minutes} 分钟"
    if minutes == _GET_INTERVAL_DESCRIPTION_THRESHOLD_60:
        return "每小时"
    if minutes < _GET_INTERVAL_DESCRIPTION_THRESHOLD_1440:
        hours = minutes // 60
        return f"每 {hours} 小时"
    if minutes == _GET_INTERVAL_DESCRIPTION_THRESHOLD_1440:
        return "每天"
    days = minutes // 1440
    return f"每 {days} 天"
