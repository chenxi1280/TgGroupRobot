"""删除系统提示配置键盘。"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _on_label(enabled: bool) -> str:
    return "✅ 启动" if enabled else "启动"


def _off_label(enabled: bool) -> str:
    return "❌ 关闭" if not enabled else "关闭"


def auto_delete_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    """删除系统提示配置键盘，按文档三列布局。"""
    buttons = [
        [
            InlineKeyboardButton("进群消息：", callback_data=f"autodel:noop:join:{chat_id}"),
            InlineKeyboardButton(_on_label(bool(settings.auto_delete_join)), callback_data=f"autodel:set:join:1:{chat_id}"),
            InlineKeyboardButton(_off_label(bool(settings.auto_delete_join)), callback_data=f"autodel:set:join:0:{chat_id}"),
        ],
        [
            InlineKeyboardButton("退群消息：", callback_data=f"autodel:noop:left:{chat_id}"),
            InlineKeyboardButton(_on_label(bool(settings.auto_delete_left)), callback_data=f"autodel:set:left:1:{chat_id}"),
            InlineKeyboardButton(_off_label(bool(settings.auto_delete_left)), callback_data=f"autodel:set:left:0:{chat_id}"),
        ],
        [
            InlineKeyboardButton("置顶通知：", callback_data=f"autodel:noop:pinned:{chat_id}"),
            InlineKeyboardButton(_on_label(bool(settings.auto_delete_pinned)), callback_data=f"autodel:set:pinned:1:{chat_id}"),
            InlineKeyboardButton(_off_label(bool(settings.auto_delete_pinned)), callback_data=f"autodel:set:pinned:0:{chat_id}"),
        ],
        [
            InlineKeyboardButton("修改群头像：", callback_data=f"autodel:noop:avatar:{chat_id}"),
            InlineKeyboardButton(_on_label(bool(settings.auto_delete_avatar)), callback_data=f"autodel:set:avatar:1:{chat_id}"),
            InlineKeyboardButton(_off_label(bool(settings.auto_delete_avatar)), callback_data=f"autodel:set:avatar:0:{chat_id}"),
        ],
        [
            InlineKeyboardButton("修改群名字：", callback_data=f"autodel:noop:title:{chat_id}"),
            InlineKeyboardButton(_on_label(bool(settings.auto_delete_title)), callback_data=f"autodel:set:title:1:{chat_id}"),
            InlineKeyboardButton(_off_label(bool(settings.auto_delete_title)), callback_data=f"autodel:set:title:0:{chat_id}"),
        ],
        [
            InlineKeyboardButton("匿名消息：", callback_data=f"autodel:noop:anonymous:{chat_id}"),
            InlineKeyboardButton(_on_label(bool(settings.auto_delete_anonymous)), callback_data=f"autodel:set:anonymous:1:{chat_id}"),
            InlineKeyboardButton(_off_label(bool(settings.auto_delete_anonymous)), callback_data=f"autodel:set:anonymous:0:{chat_id}"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]
    return InlineKeyboardMarkup(buttons)
