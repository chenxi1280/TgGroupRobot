from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def sm_repeat_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:60"),
            InlineKeyboardButton("2 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:120"),
            InlineKeyboardButton("3 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:180"),
        ],
        [
            InlineKeyboardButton("4 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:240"),
            InlineKeyboardButton("6 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:360"),
            InlineKeyboardButton("8 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:480"),
        ],
        [
            InlineKeyboardButton("12 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:720"),
            InlineKeyboardButton("24 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:1440"),
        ],
        [
            InlineKeyboardButton("10 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:10"),
            InlineKeyboardButton("15 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:15"),
        ],
        [
            InlineKeyboardButton("20 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:20"),
            InlineKeyboardButton("30 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:30"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")],
    ])


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


def sm_edit_text_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")]])


def sm_edit_media_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")]])


def sm_edit_buttons_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")]])
