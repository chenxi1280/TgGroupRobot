"""数据辅助格式化函数

提供键盘层常用的数据格式化辅助函数。
"""
from __future__ import annotations

import datetime as dt

from backend.shared.services.formatters import UserDisplaySource, format_user_display_name


def format_user_label(
    user: UserDisplaySource | None,
    user_id: int | None = None,
    default: str = "未知用户",
) -> str:
    """格式化用户显示名称

    优先级：username > first_name + last_name > "用户{id}" > default

    Args:
        user: 统一用户字段对象
        user_id: 用户 ID（当 user 为 None 时使用）
        default: 默认显示名称

    Returns:
        格式化后的用户名称

    Example:
        >>> from types import SimpleNamespace
        >>> user = SimpleNamespace(id=123, first_name="张", last_name="三", username=None)
        >>> format_user_label(user)
        '张 三'
        >>> format_user_label(None, 456)
        '用户456'
    """
    return format_user_display_name(user, user_id, default=default)


def format_participant_count(
    current: int,
    maximum: int | None = None,
    suffix: str = "人",
) -> str:
    """格式化参与人数显示

    Args:
        current: 当前参与人数
        maximum: 最大参与人数（None 表示无限制）
        suffix: 后缀文本

    Returns:
        格式化后的人数文本

    Example:
        >>> format_participant_count(5, 10)
        '(5/10人)'
        >>> format_participant_count(5)
        '(5人)'
        >>> format_participant_count(0, 100)
        '(0/100人)'
    """
    if maximum:
        return f"({current}/{maximum}{suffix})"
    return f"({current}{suffix})"


def format_datetime(
    datetime_obj: dt.datetime | None,
    format_str: str = "%m-%d %H:%M",
    timezone_offset: int = 8,
    *, default: str = "",
) -> str:
    """格式化日期时间

    Args:
        datetime_obj: 日期时间对象
        format_str: 格式化字符串
        timezone_offset: 时区偏移（小时），默认为北京时间 UTC+8
        default: 默认值（当 datetime_obj 为 None 时返回）

    Returns:
        格式化后的时间字符串

    Example:
        >>> from datetime import datetime, timezone, timedelta
        >>> dt = datetime(2025, 1, 14, 10, 30, tzinfo=timezone.utc)
        >>> format_datetime(dt)
        '01-14 18:30'
        >>> format_datetime(None)
        ''
    """
    if datetime_obj is None:
        return default

    # 转换时区
    if timezone_offset != 0:
        datetime_obj = datetime_obj + dt.timedelta(hours=timezone_offset)

    return datetime_obj.strftime(format_str)


def format_schedule_info(
    schedule_time: dt.datetime | None,
    frequency: str | None = None,
    timezone_offset: int = 8,
) -> str:
    """格式化定时信息（用于广告、定时消息等）

    Args:
        schedule_time: 计划时间
        frequency: 频率描述
        timezone_offset: 时区偏移（小时）

    Returns:
        格式化后的定时信息字符串

    Example:
        >>> from datetime import datetime, timezone, timedelta
        >>> dt = datetime(2025, 1, 14, 10, 30, tzinfo=timezone.utc)
        >>> format_schedule_info(dt, "每天")
        ' 01-14 18:30 [每天]'
        >>> format_schedule_info(None, "单次")
        ' [单次]'
        >>> format_schedule_info(None, None)
        ''
    """
    parts = []

    if schedule_time:
        time_str = format_datetime(schedule_time, "%m-%d %H:%M", timezone_offset)
        parts.append(f" {time_str}")

    if frequency:
        parts.append(f" [{frequency}]")
    elif schedule_time:  # 有时间但无频率，默认为单次
        parts.append(" [单次]")

    return "".join(parts)


def truncate_text(
    text: str,
    max_length: int,
    suffix: str = "...",
) -> str:
    """截断文本到指定长度

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的文本

    Example:
        >>> truncate_text("这是一段很长的文本", 5)
        '这是一段...'
        >>> truncate_text("短文本", 10)
        '短文本'
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def format_item_label(
    title: str,
    status_icon: str = "",
    extra_info: str = "",
    *, max_length: int | None = None,
) -> str:
    """格式化项目标签（用于列表项）

    Args:
        title: 标题
        status_icon: 状态图标
        extra_info: 额外信息
        max_length: 最大长度（None 表示不限制）

    Returns:
        格式化后的标签

    Example:
        >>> format_item_label("测试项目", "🟢", "(5/10人)")
        '🟢 测试项目 (5/10人)'
        >>> format_item_label("很长的标题很长的标题很长的标题", "🔴", "", 15)
        '🔴 很长的标题很长的标...'
    """
    parts = []

    if status_icon:
        parts.append(status_icon)

    if title:
        parts.append(title)

    if extra_info:
        parts.append(extra_info)

    label = " ".join(parts)

    if max_length and len(label) > max_length:
        label = truncate_text(label, max_length)

    return label


def format_count_info(
    count: int,
    label: str = "",
    show_zero: bool = True,
) -> str:
    """格式化计数信息

    Args:
        count: 数量
        label: 标签文本
        show_zero: 是否显示零

    Returns:
        格式化后的计数信息

    Example:
        >>> format_count_info(5, "条消息")
        '5条消息'
        >>> format_count_info(0, "条消息", show_zero=False)
        ''
        >>> format_count_info(3)
        '3'
    """
    if count == 0 and not show_zero:
        return ""

    return f"{count}{label}" if label else str(count)


def format_bool_label(
    value: bool,
    true_label: str = "是",
    false_label: str = "否",
    *, true_icon: str = "✅",
    false_icon: str = "❌",
) -> str:
    """格式化布尔值标签

    Args:
        value: 布尔值
        true_label: 真值标签
        false_label: 假值标签
        true_icon: 真值图标
        false_icon: 假值图标

    Returns:
        格式化后的标签

    Example:
        >>> format_bool_label(True)
        '✅ 是'
        >>> format_bool_label(False)
        '❌ 否'
        >>> format_bool_label(True, "启用", "禁用", "🟢", "🔴")
        '🟢 启用'
    """
    icon = true_icon if value else false_icon
    label = true_label if value else false_label
    return f"{icon} {label}"


def format_range(
    current: int,
    total: int,
    separator: str = "/",
) -> str:
    """格式化范围信息

    Args:
        current: 当前值
        total: 总值
        separator: 分隔符

    Returns:
        格式化后的范围字符串

    Example:
        >>> format_range(5, 10)
        '5/10'
        >>> format_range(1, 1)
        '1/1'
    """
    return f"{current}{separator}{total}"
