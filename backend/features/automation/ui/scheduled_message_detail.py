from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.time_helper import format_timestamp, get_interval_description
from backend.shared.ui.base.helpers import create_back_button


def sm_detail_keyboard(task, chat_id: int) -> InlineKeyboardMarkup:
    text_preview = ""
    if task.text:
        text_preview = task.text[:30] + "..." if len(task.text) > 30 else task.text

    period_desc = "全天" if task.day_start_hour == 0 and task.day_end_hour == 23 else (
        f"{task.day_start_hour:02d}:00-{task.day_end_hour:02d}:00"
    )

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{'🟢' if task.enabled else '🔴'} 启用",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:enabled:{1 if not task.enabled else 0}",
            ),
            InlineKeyboardButton(
                f"{'✅' if task.delete_previous else '❌'} 删除上条",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:delete_previous:{1 if not task.delete_previous else 0}",
            ),
            InlineKeyboardButton(
                f"{'📌' if task.pin_message else '⬜'} 置顶",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:pin_message:{1 if not task.pin_message else 0}",
            ),
        ],
        [InlineKeyboardButton(f"📝 文本: {text_preview if task.text else '(空)'}", callback_data=f"sm:edit:{chat_id}:{task.short_id}:text")],
        [InlineKeyboardButton(f"🎬 媒体: {task.media_type}", callback_data=f"sm:edit:{chat_id}:{task.short_id}:media")],
        [InlineKeyboardButton(f"🔗 按钮: {len(task.buttons)} 行", callback_data=f"sm:edit:{chat_id}:{task.short_id}:buttons")],
        [InlineKeyboardButton(f"⏰ 重复: {get_interval_description(task.repeat_interval_min)}", callback_data=f"sm:edit:{chat_id}:{task.short_id}:repeat")],
        [InlineKeyboardButton(f"🕐 时段: {period_desc}", callback_data=f"sm:edit:{chat_id}:{task.short_id}:day_period")],
        [InlineKeyboardButton(f"📅 开始: {format_timestamp(task.start_at) if task.start_at else '(未设置)'}", callback_data=f"sm:edit:{chat_id}:{task.short_id}:start_at")],
        [InlineKeyboardButton(f"📅 终止: {format_timestamp(task.end_at) if task.end_at else '(未设置)'}", callback_data=f"sm:edit:{chat_id}:{task.short_id}:end_at")],
        [
            InlineKeyboardButton("🗑️ 删除任务", callback_data=f"sm:del_confirm:{chat_id}:{task.short_id}"),
            create_back_button(chat_id, "sm:list"),
        ],
    ])
