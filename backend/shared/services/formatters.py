"""通用格式化工具函数"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.platform.db.schema.models.core import TgUser


def format_user_mention(user: "TgUser", use_html: bool = False) -> str:
    """
    格式化用户提法（@用户）

    Args:
        user: 用户对象
        use_html: 是否使用 HTML 格式（默认 Markdown）

    Returns:
        格式化后的用户提法字符串
    """
    if use_html:
        # HTML 格式
        if user.username:
            return f"@{user.username}"
        return f"<a href=\"tg://user?id={user.id}\">{user.full_name or '用户'}</a>"
    else:
        # Markdown 格式
        if user.username:
            return f"@{user.username}"
        return f"[{user.full_name or '用户'}](tg://user?id={user.id})"


def format_datetime(dt: dt.datetime, format_str: str = "%Y-%m-%d %H:%M") -> str:
    """
    格式化日期时间

    Args:
        dt: 日期时间对象
        format_str: 格式字符串

    Returns:
        格式化后的日期时间字符串
    """
    if dt is None:
        return "未设置"

    if dt.tzinfo is None:
        # 如果没有时区信息，假设是 UTC
        dt = dt.replace(tzinfo=dt.timezone.utc)

    return dt.strftime(format_str)


def format_timedelta(delta: dt.timedelta) -> str:
    """
    格式化时间差为人类可读的字符串

    Args:
        delta: 时间差对象

    Returns:
        格式化后的时间差字符串（如 "2天3小时"）
    """
    if delta is None:
        return "未知"

    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}秒"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes}分钟"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}小时{minutes}分钟"
        return f"{hours}小时"
    else:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        if hours > 0:
            return f"{days}天{hours}小时"
        return f"{days}天"


def format_number(number: int, use_emoji: bool = False) -> str:
    """
    格式化数字（添加千位分隔符）

    Args:
        number: 要格式化的数字
        use_emoji: 是否使用表情符号（1234 → 1.2k）

    Returns:
        格式化后的数字字符串
    """
    if use_emoji and number >= 1000:
        # 使用表情符号格式化
        if number >= 1000000:
            return f"{number / 1000000:.1f}M"
        return f"{number / 1000:.1f}k"
    else:
        # 使用千位分隔符
        return f"{number:,}"


def format_percentage(value: int, total: int, decimals: int = 1) -> str:
    """
    格式化百分比

    Args:
        value: 数值
        total: 总数
        decimals: 小数位数

    Returns:
        格式化后的百分比字符串
    """
    if total == 0:
        return "0%"

    percentage = (value / total) * 100
    return f"{percentage:.{decimals}f}%"


def format_ranking(rank: int) -> str:
    """
    格式化排名（添加序数后缀）

    Args:
        rank: 排名数字

    Returns:
        格式化后的排名字符串（如 "第1名"、"第2名"）
    """
    return f"第{rank}名"


def format_points(points: int, show_plus: bool = False) -> str:
    """
    格式化积分数值

    Args:
        points: 积分数
        show_plus: 是否显示加号（正数显示为 +100）

    Returns:
        格式化后的积分字符串
    """
    if show_plus and points > 0:
        return f"+{points:,}"
    return f"{points:,}"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断过长的文本

    Args:
        text: 要截断的文本
        max_length: 最大长度
        suffix: 截断后添加的后缀

    Returns:
        截断后的文本
    """
    if text is None:
        return ""

    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def format_list(items: list[str], max_items: int = 5, separator: str = "、") -> str:
    """
    格式化列表为字符串

    Args:
        items: 列表项
        max_items: 最多显示的项目数
        separator: 分隔符

    Returns:
        格式化后的字符串
    """
    if not items:
        return "无"

    if len(items) <= max_items:
        return separator.join(items)

    return separator.join(items[:max_items]) + f"等{len(items)}项"
