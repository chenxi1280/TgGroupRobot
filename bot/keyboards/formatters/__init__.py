"""键盘格式化工具

提供 keyboards 层内部的格式化逻辑，将数据处理从键盘生成函数中抽离。
"""
from bot.keyboards.formatters.data_helpers import (
    format_bool_label,
    format_count_info,
    format_datetime,
    format_item_label,
    format_participant_count,
    format_range,
    format_schedule_info,
    format_user_label,
    truncate_text,
)
from bot.keyboards.formatters.status_icons import (
    Icon,
    StatusIconSet,
    StatusIcons,
)

__all__ = [
    # Status icons
    "StatusIcons",
    "StatusIconSet",
    "Icon",
    # Data helpers
    "format_user_label",
    "format_participant_count",
    "format_datetime",
    "format_schedule_info",
    "truncate_text",
    "format_item_label",
    "format_count_info",
    "format_bool_label",
    "format_range",
]
