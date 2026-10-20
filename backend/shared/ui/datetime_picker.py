"""Telegram date/time controls. Rendering never applies a business setting."""
from __future__ import annotations

import calendar
import datetime as dt
import secrets

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup

from backend.shared.services.base import ValidationError
from backend.shared.time_helper import LOCAL_TIMEZONE, parse_date_time_string
from backend.shared.ui.copy import copy_button

KEY = "__datetime_picker__"
MIN_YEAR, MAX_YEAR = 1970, 2199
MINUTES_PER_PAGE = 20
SUPPORTED_STATES = {
    "sm_edit_start_at", "sm_edit_end_at", "ads_rule_edit_start",
    "ads_item_edit_start", "ads_item_edit_end",
}


def new_picker(back: str, initial: str) -> dict:
    timestamp = parse_date_time_string(initial)
    if timestamp is None:
        raise ValidationError("时间示例格式无效")
    value = dt.datetime.fromtimestamp(timestamp, LOCAL_TIMEZONE)
    return {"token": secrets.token_hex(6), "revision": 0, "back": back,
            "value": value.strftime("%Y-%m-%d %H:%M"), "month": value.strftime("%Y-%m"),
            "step": "input", "minute_page": value.minute // MINUTES_PER_PAGE,
            "expires": int(dt.datetime.now(dt.UTC).timestamp()) + 1800}


def entry_button(picker: dict) -> Button:
    return _button(picker, "📅 日历选择", "open")


def _button(picker: dict, label: str, action: str, *, value: str = "") -> Button:
    if picker.get("prefix") == "acal":
        return Button(label, callback_data=f"acal:{picker['token']}:{picker['revision']}:{action}:{value}")
    return Button(label, callback_data=f"dtp:{picker['token']}:{picker['revision']}:{action}:{value}")


def _grid(buttons, columns=4):
    return [buttons[index:index + columns] for index in range(0, len(buttons), columns)]


def _month_rows(picker):
    year, month = map(int, picker["month"].split("-"))
    chosen = dt.datetime.strptime(picker["value"], "%Y-%m-%d %H:%M")
    rows = [[_button(picker, "‹ 上个月", "month", value="-1"),
             _button(picker, picker["month"], "noop"),
             _button(picker, "下个月 ›", "month", value="1")]]
    rows.append([_button(picker, label, "noop") for label in "一二三四五六日"])
    for week in calendar.monthcalendar(year, month):
        row = []
        for day in week:
            if not day:
                row.append(_button(picker, "·", "noop"))
            else:
                value = dt.date(year, month, day)
                prefix = "✓" if value == chosen.date() else ""
                row.append(_button(picker, f"{prefix}{day}", "day", value=value.isoformat()))
        rows.append(row)
    rows.append([_button(picker, "去年", "month", value="-12"),
                 _button(picker, "今年本月", "today"),
                 _button(picker, "明年", "month", value="12")])
    return rows


def _hour_rows(picker, chosen):
    rows = _grid([_button(picker, ("✓ " if hour == chosen.hour else "") + f"{hour:02d}:00",
                         "hour", value=str(hour)) for hour in range(24)])
    rows.append([_button(picker, "返回日期", "back", value="day")])
    return rows


def _minute_rows(picker, chosen):
    start = picker["minute_page"] * MINUTES_PER_PAGE
    rows = _grid([_button(picker, ("✓ " if minute == chosen.minute else "") + f"{minute:02d}分",
                         "minute", value=str(minute)) for minute in range(start, start + MINUTES_PER_PAGE)])
    rows.append([_button(picker, f"{p * 20:02d}—{p * 20 + 19:02d}分", "minutes", value=str(p)) for p in range(3)])
    rows.append([_button(picker, "返回小时", "back", value="hour")])
    return rows


def _confirm_rows(picker, chosen):
    return [[copy_button("复制所选时间", picker["value"])],
            [_button(picker, "修改日期", "back", value="day"), _button(picker, "修改时间", "back", value="hour")],
            [_button(picker, "确认应用", "apply")]]


def picker_view(picker: dict, *, scope: str) -> tuple[str, InlineKeyboardMarkup]:
    step = picker["step"]
    chosen = dt.datetime.strptime(picker["value"], "%Y-%m-%d %H:%M")
    renderers = {"day": (lambda p, c: _month_rows(p), "选择日期"),
                 "hour": (_hour_rows, "选择小时"), "minute": (_minute_rows, "选择分钟"),
                 "confirm": (_confirm_rows, "确认后才保存到当前字段")}
    if step in renderers:
        render, hint = renderers[step]
        rows = render(picker, chosen)
        rows.append([_button(picker, "手动输入", "manual"), _button(picker, "取消并返回", "cancel")])
    else:
        rows = [[copy_button("复制时间", picker["value"]), entry_button(picker)],
                [_button(picker, "取消并返回", "cancel")]]
        hint = "输入 YYYY-MM-DD HH:MM，或使用日历；发送后按原输入规则保存"
    text = f"📅 日期与时间 · 北京时间 UTC+8\n{scope}\n当前选择：{picker['value']}\n\n{hint}。"
    if step != "input":
        text += "\n翻月和选时不会保存；请完成确认或取消。"
    return text, InlineKeyboardMarkup(rows)


def _move_month(result, chosen, value):
    offset = int(value)
    if offset not in {-12, -1, 1, 12}:
        raise ValidationError("无效月份")
    year, month = map(int, result["month"].split("-"))
    year, month = divmod(year * 12 + month - 1 + offset, 12)
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValidationError(f"日历支持 {MIN_YEAR}—{MAX_YEAR} 年；其他日期请手动输入")
    result["month"] = f"{year:04d}-{month + 1:02d}"
    return chosen


def _select_day(result, chosen, value):
    date = dt.date.fromisoformat(value)
    if date.strftime("%Y-%m") != result["month"]:
        raise ValidationError("请使用当前月份的日期按钮")
    result["step"] = "hour"
    return chosen.replace(year=date.year, month=date.month, day=date.day)


def _select_hour(result, chosen, value):
    result["step"] = "minute"
    return chosen.replace(hour=int(value))


def _select_minute(result, chosen, value):
    minute = int(value)
    if minute // MINUTES_PER_PAGE != result["minute_page"]:
        raise ValidationError("请使用当前分钟页")
    result["step"] = "confirm"
    return chosen.replace(minute=minute)


def _minute_page(result, chosen, value):
    if int(value) not in range(3):
        raise ValidationError("无效分钟页")
    result["minute_page"] = int(value)
    return chosen


def _go_back(result, chosen, value):
    if value not in {"day", "hour"}:
        raise ValidationError("无效返回步骤")
    result["step"] = value
    return chosen


def _open(result, chosen, value):
    result["step"] = "day"
    return chosen


def _today(result, chosen, value):
    result["month"] = dt.datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m")
    return chosen


def _manual(result, chosen, value):
    result["step"] = "input"
    return chosen


TRANSITIONS = {
    "open": ({"input"}, _open), "month": ({"day"}, _move_month),
    "today": ({"day"}, _today), "day": ({"day"}, _select_day),
    "hour": ({"hour"}, _select_hour), "minutes": ({"minute"}, _minute_page),
    "minute": ({"minute"}, _select_minute), "back": ({"hour", "minute", "confirm"}, _go_back),
    "manual": ({"input", "day", "hour", "minute", "confirm"}, _manual),
}


def transition(picker: dict, action: str, value: str) -> dict:
    """Validate the step and payload before advancing the picker revision."""
    config = TRANSITIONS.get(action)
    if config is None or picker["step"] not in config[0]:
        raise ValidationError("此操作不适用于当前步骤，请使用最新按钮")
    result = dict(picker)
    chosen = dt.datetime.strptime(picker["value"], "%Y-%m-%d %H:%M")
    chosen = config[1](result, chosen, value)
    result["value"] = chosen.strftime("%Y-%m-%d %H:%M")
    result["revision"] += 1
    return result
