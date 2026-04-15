from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.time_helper import get_interval_description
from backend.shared.ui.message_config_panel import action_button, button_count, mark_configured


def sm_detail_keyboard(task, chat_id: int) -> InlineKeyboardMarkup:
    title_configured = bool(str(getattr(task, "title", "") or "").strip() and task.title != "定时消息")
    media_configured = getattr(task, "media_type", "none") != "none" and bool(getattr(task, "media_file_id", None))
    text_configured = bool(str(getattr(task, "text", "") or "").strip())
    buttons_configured = button_count(getattr(task, "buttons", None)) > 0
    time_configured = bool(getattr(task, "start_at", None) or getattr(task, "end_at", None))
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ 状态:", callback_data=f"sm:open:{chat_id}:{task.short_id}"),
            InlineKeyboardButton(mark_configured("启用", bool(task.enabled)), callback_data=f"sm:set:{chat_id}:{task.short_id}:enabled:1"),
            InlineKeyboardButton(mark_configured("关闭", not bool(task.enabled)), callback_data=f"sm:set:{chat_id}:{task.short_id}:enabled:0"),
        ],
        [
            action_button("标题备注", f"sm:edit:{chat_id}:{task.short_id}:title", configured=title_configured),
            action_button("设置封面", f"sm:edit:{chat_id}:{task.short_id}:media", configured=media_configured),
        ],
        [
            action_button("设置文本", f"sm:edit:{chat_id}:{task.short_id}:text", configured=text_configured),
            action_button("设置按钮", f"sm:edit:{chat_id}:{task.short_id}:buttons", configured=buttons_configured),
        ],
        [
            action_button("时间范围", f"sm:edit:{chat_id}:{task.short_id}:time_range", configured=time_configured),
            InlineKeyboardButton(f"发送频率：{get_interval_description(task.repeat_interval_min)}", callback_data=f"sm:edit:{chat_id}:{task.short_id}:repeat"),
        ],
        [
            InlineKeyboardButton("⚙️ 置顶:", callback_data=f"sm:open:{chat_id}:{task.short_id}"),
            InlineKeyboardButton(mark_configured("启用", bool(task.pin_message)), callback_data=f"sm:set:{chat_id}:{task.short_id}:pin_message:1"),
            InlineKeyboardButton(mark_configured("关闭", not bool(task.pin_message)), callback_data=f"sm:set:{chat_id}:{task.short_id}:pin_message:0"),
        ],
        [
            InlineKeyboardButton("🧹 删除上条:", callback_data=f"sm:open:{chat_id}:{task.short_id}"),
            InlineKeyboardButton(mark_configured("启用", bool(task.delete_previous)), callback_data=f"sm:set:{chat_id}:{task.short_id}:delete_previous:1"),
            InlineKeyboardButton(mark_configured("关闭", not bool(task.delete_previous)), callback_data=f"sm:set:{chat_id}:{task.short_id}:delete_previous:0"),
        ],
        [
            InlineKeyboardButton("🏖️ 预览效果", callback_data=f"sm:preview:{chat_id}:{task.short_id}"),
            InlineKeyboardButton("❌ 删除配置", callback_data=f"sm:del_confirm:{chat_id}:{task.short_id}"),
        ],
        [
            InlineKeyboardButton("🔙 返回", callback_data=f"sm:list:{chat_id}:0"),
        ],
    ])
