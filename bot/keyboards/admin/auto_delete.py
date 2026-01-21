"""自动删除配置键盘

提供自动删除管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_separator


def auto_delete_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    """自动删除配置键盘"""
    # 主开关状态
    main_status = "✅ 开启" if settings.auto_delete_enabled else "❌ 关闭"

    # 各项开关状态（添加文字说明）
    join_status = "✅ 开启" if settings.auto_delete_join else "❌ 关闭"
    left_status = "✅ 开启" if settings.auto_delete_left else "❌ 关闭"
    pinned_status = "✅ 开启" if settings.auto_delete_pinned else "❌ 关闭"
    avatar_status = "✅ 开启" if settings.auto_delete_avatar else "❌ 关闭"
    title_status = "✅ 开启" if settings.auto_delete_title else "❌ 关闭"
    anon_status = "✅ 开启" if settings.auto_delete_anonymous else "❌ 关闭"

    separator = create_separator()

    buttons = [
        # 主开关
        [InlineKeyboardButton(f"🧹 自动删除: {main_status}", callback_data=f"autodel:toggle:enabled:{chat_id}")],
        # 分隔线
        [separator],
        # 各项开关（格式：项目: 状态）
        [InlineKeyboardButton(f"进群: {join_status}", callback_data=f"autodel:toggle:join:{chat_id}")],
        [InlineKeyboardButton(f"退群: {left_status}", callback_data=f"autodel:toggle:left:{chat_id}")],
        [InlineKeyboardButton(f"置顶: {pinned_status}", callback_data=f"autodel:toggle:pinned:{chat_id}")],
        [InlineKeyboardButton(f"头像: {avatar_status}", callback_data=f"autodel:toggle:avatar:{chat_id}")],
        [InlineKeyboardButton(f"群名: {title_status}", callback_data=f"autodel:toggle:title:{chat_id}")],
        [InlineKeyboardButton(f"匿名: {anon_status}", callback_data=f"autodel:toggle:anonymous:{chat_id}")],
        # 返回
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]
    return InlineKeyboardMarkup(buttons)
