from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.time_ui import build_interval_keyboard


def sm_repeat_keyboard(chat_id: int, task_id: str, current_repeat_min: int) -> InlineKeyboardMarkup:
    return build_interval_keyboard(
        current_minutes=current_repeat_min,
        option_rows=[
            [10, 15, 20, 30],
            [60, 120, 180, 240],
            [360, 480, 720, 1440],
        ],
        callback_factory=lambda value: f"sm:set:{chat_id}:{task_id}:repeat:{value}",
        back_callback=f"sm:open:{chat_id}:{task_id}",
    )


def sm_day_period_start_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for hour in range(24):
        row.append(InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"sm:set:{chat_id}:{task_id}:day_start:{hour}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")])
    return InlineKeyboardMarkup(buttons)


def sm_day_period_end_keyboard(chat_id: int, task_id: str, start_hour: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for hour in range(24):
        row.append(InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"sm:set:{chat_id}:{task_id}:day_end:{hour}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.insert(0, [InlineKeyboardButton(f"已选择开始时间: {start_hour:02d}:00，请选择结束时间", callback_data="_noop")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")])
    return InlineKeyboardMarkup(buttons)


def sm_confirm_delete_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"sm:del_do:{chat_id}:{task_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"sm:del_cancel:{chat_id}:{task_id}"),
        ],
    ])


def sm_time_range_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("开始时间", callback_data=f"sm:edit:{chat_id}:{task_id}:start_at"),
            InlineKeyboardButton("结束时间", callback_data=f"sm:edit:{chat_id}:{task_id}:end_at"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")],
    ])


def sm_edit_text_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")]])


def sm_edit_media_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")]])


def sm_edit_buttons_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")]])
