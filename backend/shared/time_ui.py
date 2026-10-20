from __future__ import annotations

import datetime as dt
import html
from collections.abc import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.time_helper import LOCAL_TIMEZONE, format_duration_minutes
from backend.shared.ui.copy import copy_button
_FORMAT_INTERVAL_MINUTES_LABEL_THRESHOLD_1440 = 1440
_FORMAT_INTERVAL_MINUTES_LABEL_THRESHOLD_60 = 60



def next_top_of_hour(now: dt.datetime | None = None, *, days_offset: int = 0) -> dt.datetime:
    current = (now or dt.datetime.now(dt.UTC)).astimezone(LOCAL_TIMEZONE)
    rounded = current.replace(minute=0, second=0, microsecond=0)
    if current > rounded:
        rounded += dt.timedelta(hours=1)
    if days_offset:
        rounded += dt.timedelta(days=days_offset)
    return rounded.astimezone(dt.UTC)


def build_datetime_prompt_text(
    *,
    title: str,
    sample_time_text: str,
    input_hint: str,
    extra_tips: list[str] | None = None,
    sample_time_unix: int | None = None,
    show_copy_hint: bool = True,
) -> str:
    tips = extra_tips or []
    tip_lines = "\n".join(tips)
    if tip_lines:
        tip_lines = f"{tip_lines}\n\n"
    sample_text = html.escape(sample_time_text)
    sample_markup = f"<code>{sample_text}</code>"
    copy_hint = "点击复制示例，再粘贴到输入框修改并发送；复制本身不会保存。\n\n" if show_copy_hint else ""
    return (
        f"{title}\n\n"
        "时区：北京时间 UTC+8\n格式：YYYY-MM-DD HH:MM\n"
        f"完整示例：{sample_markup}\n\n"
        f"{copy_hint}"
        f"{tip_lines}{input_hint}"
    )


def build_back_keyboard(back_callback: str | None) -> InlineKeyboardMarkup:
    if not back_callback:
        return InlineKeyboardMarkup([])
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=back_callback)]])


def build_copy_time_keyboard(back_callback: str | None, sample_time_text: str, *, current_value: str | None = None, picker: dict | None = None) -> InlineKeyboardMarkup:
    row = [copy_button("📋 复制示例", sample_time_text)]
    if current_value:
        row.insert(0, copy_button("复制当前值", current_value))
    rows = [row]
    if picker:
        from backend.shared.ui.datetime_picker import entry_button
        rows.append([entry_button(picker)])
    if back_callback:
        rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def build_copy_options_keyboard(back_callback: str | None, options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons = [copy_button(label, value) for label, value in options]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    if back_callback:
        rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def next_top_of_hour_hhmm(now: dt.datetime | None = None, *, hours_offset: int = 0) -> str:
    rounded = next_top_of_hour(now)
    if hours_offset:
        rounded += dt.timedelta(hours=hours_offset)
    return rounded.astimezone(LOCAL_TIMEZONE).strftime("%H:%M")


def build_hhmm_prompt_text(
    *,
    title: str,
    sample_time_text: str,
    input_hint: str,
    extra_tips: list[str] | None = None,
) -> str:
    tips = extra_tips or []
    tip_lines = "\n".join(tips)
    if tip_lines:
        tip_lines = f"{tip_lines}\n\n"
    return (
        f"{title}\n\n"
        "时区：北京时间 UTC+8\n格式：HH:MM\n"
        f"完整示例：<code>{html.escape(sample_time_text)}</code>\n\n"
        "点击复制示例，再粘贴修改并发送；复制本身不会保存。\n\n"
        f"{tip_lines}{input_hint}"
    )


def build_minutes_or_hhmm_prompt_text(
    *,
    title: str,
    minutes_sample_text: str,
    hhmm_sample_text: str,
    input_hint: str,
    extra_tips: list[str] | None = None,
) -> str:
    tips = extra_tips or []
    tip_lines = "\n".join(tips)
    if tip_lines:
        tip_lines = f"{tip_lines}\n\n"
    return (
        f"{title}\n\n"
        "支持两种格式：分钟数 或 HH:MM\n"
        f"完整示例：<code>{html.escape(minutes_sample_text)}</code> 或 <code>{html.escape(hhmm_sample_text)}</code>\n\n"
        f"快捷示例：<code>{html.escape(minutes_sample_text)}</code> / <code>{html.escape(hhmm_sample_text)}</code>\n"
        "点击复制示例，再粘贴修改并发送；复制本身不会保存。\n\n"
        f"{tip_lines}{input_hint}"
    )


def build_numeric_duration_prompt_text(
    *,
    title: str,
    unit_label: str,
    sample_value_text: str,
    input_hint: str,
    extra_tips: list[str] | None = None,
) -> str:
    tips = extra_tips or []
    tip_lines = "\n".join(tips)
    if tip_lines:
        tip_lines = f"{tip_lines}\n\n"
    return (
        f"{title}\n\n"
        f"格式：纯数字（单位：{unit_label}）\n"
        f"完整示例：<code>{html.escape(sample_value_text)}</code>\n\n"
        f"快捷示例：<code>{html.escape(sample_value_text)}</code>\n"
        "点击复制示例，再粘贴修改并发送；复制本身不会保存。\n\n"
        f"{tip_lines}{input_hint}"
    )


def format_interval_minutes_label(minutes: int) -> str:
    return format_duration_minutes(minutes)


def build_interval_keyboard(
    *,
    current_minutes: int,
    option_rows: list[list[int]],
    callback_factory: Callable[[int], str],
    back_callback: str,
    title: str | None = None,
    custom_callback: str | None = None,
    custom_label: str = "自定义时间",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if title:
        rows.append([InlineKeyboardButton(title, callback_data="_noop")])
    for option_row in option_rows:
        row: list[InlineKeyboardButton] = []
        for value in option_row:
            prefix = "✅ " if value == current_minutes else ""
            row.append(
                InlineKeyboardButton(
                    f"{prefix}{format_interval_minutes_label(value)}",
                    callback_data=callback_factory(value),
                )
            )
        rows.append(row)
    if custom_callback:
        rows.append([InlineKeyboardButton(custom_label, callback_data=custom_callback)])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)
