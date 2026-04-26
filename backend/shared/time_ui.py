from __future__ import annotations

import datetime as dt
import html
from collections.abc import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.time_helper import LOCAL_TIMEZONE


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
    sample_markup = f'<tg-time unix="{int(sample_time_unix)}" format="wDT">{sample_text}</tg-time>' if sample_time_unix is not None else f"<b>{sample_text}</b>"
    copy_hint = "点击下方蓝色按钮可直接复制\n\n" if show_copy_hint else ""
    return (
        f"{title}\n\n"
        "格式：YYYY-MM-DD HH:MM\n"
        f"完整示例：{sample_markup}\n\n"
        f"最近整点示例：{sample_markup}\n"
        f"{copy_hint}"
        f"{tip_lines}{input_hint}"
    )


def build_back_keyboard(back_callback: str | None) -> InlineKeyboardMarkup:
    if not back_callback:
        return InlineKeyboardMarkup([])
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=back_callback)]])


def build_copy_time_keyboard(back_callback: str | None, sample_time_text: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"📋 复制 {sample_time_text}", api_kwargs={"copy_text": {"text": sample_time_text}})]]
    if back_callback:
        rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def build_copy_options_keyboard(back_callback: str | None, options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, api_kwargs={"copy_text": {"text": value}})]
        for label, value in options
    ]
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
        "格式：HH:MM\n"
        f"完整示例：<b>{html.escape(sample_time_text)}</b>\n\n"
        f"最近整点示例：<b>{html.escape(sample_time_text)}</b>\n"
        "点击下方蓝色按钮可直接复制\n\n"
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
        f"完整示例：<b>{html.escape(minutes_sample_text)}</b> 或 <b>{html.escape(hhmm_sample_text)}</b>\n\n"
        f"快捷示例：<b>{html.escape(minutes_sample_text)}</b> / <b>{html.escape(hhmm_sample_text)}</b>\n"
        "点击下方蓝色按钮可直接复制\n\n"
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
        f"完整示例：<b>{html.escape(sample_value_text)}</b>\n\n"
        f"快捷示例：<b>{html.escape(sample_value_text)}</b>\n"
        "点击下方蓝色按钮可直接复制\n\n"
        f"{tip_lines}{input_hint}"
    )


def format_interval_minutes_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}分钟"
    if minutes == 60:
        return "1小时"
    if minutes < 1440:
        return f"{minutes // 60}小时"
    if minutes == 1440:
        return "1天"
    return f"{minutes // 1440}天"


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
