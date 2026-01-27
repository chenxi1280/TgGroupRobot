from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.models.scheduled_message import ScheduledMessageTask


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
    # 将时间戳转换为 UTC 时间
    utc_time = dt.datetime.fromtimestamp(timestamp, dt.UTC)
    current_hour = utc_time.hour

    # 处理跨天时段
    if day_start_hour <= day_end_hour:
        # 正常时段：如 9-18
        return day_start_hour <= current_hour < day_end_hour
    else:
        # 跨天时段：如 22-6（22:00 到次日 06:00）
        return current_hour >= day_start_hour or current_hour < day_end_hour


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

    # 如果设置了 start_at 且在未来，直接返回 start_at
    if task.start_at and task.start_at > now:
        return task.start_at

    # 基于上次发送时间或开始时间计算
    base_time = last_sent_timestamp if last_sent_timestamp else task.start_at or now
    next_time = base_time + task.repeat_interval_min * 60

    # 确保在未来
    while next_time < now:
        next_time += task.repeat_interval_min * 60

    # 考虑时段窗口，找到下一个有效时间点
    if not is_time_in_window(next_time, task.day_start_hour, task.day_end_hour):
        next_time = find_next_valid_time(next_time, task)

    return next_time


def find_next_valid_time(from_timestamp: int, task: ScheduledMessageTask) -> int:
    """
    从指定时间开始，寻找下一个在时段窗口内的时间点

    Args:
        from_timestamp: 起始时间戳
        task: 定时消息任务

    Returns:
        下一个在时段窗口内的 Unix 时间戳
    """
    current = from_timestamp
    interval = task.repeat_interval_min * 60

    # 最多向前查找 30 天（防止无限循环）
    max_iterations = 30 * 24 * 60 // task.repeat_interval_min

    for _ in range(max_iterations):
        current += interval
        if is_time_in_window(current, task.day_start_hour, task.day_end_hour):
            return current

    # 如果找不到，返回原时间（应该不会发生）
    return from_timestamp


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
        dt_obj = dt.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        # 将输入时间视为本地时间，转换为 UTC
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
        return int(dt_obj.timestamp())
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
    dt_obj = timestamp_to_datetime(timestamp)
    return dt_obj.strftime(format_str)


def get_interval_description(minutes: int) -> str:
    """
    获取间隔时间的友好描述

    Args:
        minutes: 间隔分钟数

    Returns:
        友好的时间描述
    """
    if minutes < 60:
        return f"每 {minutes} 分钟"
    elif minutes == 60:
        return "每小时"
    elif minutes < 1440:
        hours = minutes // 60
        return f"每 {hours} 小时"
    elif minutes == 1440:
        return "每天"
    else:
        days = minutes // 1440
        return f"每 {days} 天"
