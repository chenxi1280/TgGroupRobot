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

    # 各项开关状态
    join_status = "✅" if settings.auto_delete_join else "❌"
    left_status = "✅" if settings.auto_delete_left else "❌"
    pinned_status = "✅" if settings.auto_delete_pinned else "❌"
    avatar_status = "✅" if settings.auto_delete_avatar else "❌"
    title_status = "✅" if settings.auto_delete_title else "❌"
    anon_status = "✅" if settings.auto_delete_anonymous else "❌"

    separator = create_separator()

    buttons = [
        # 主开关
        [InlineKeyboardButton(f"🧹 自动删除: {main_status}", callback_data=f"autodel:toggle:enabled:{chat_id}")],
        # 分隔线
        [separator],
        # 各项开关
        [InlineKeyboardButton(f"{join_status} 进群消息", callback_data=f"autodel:toggle:join:{chat_id}")],
        [InlineKeyboardButton(f"{left_status} 退群消息", callback_data=f"autodel:toggle:left:{chat_id}")],
        [InlineKeyboardButton(f"{pinned_status} 置顶消息", callback_data=f"autodel:toggle:pinned:{chat_id}")],
        [InlineKeyboardButton(f"{avatar_status} 修改头像", callback_data=f"autodel:toggle:avatar:{chat_id}")],
        [InlineKeyboardButton(f"{title_status} 修改名称", callback_data=f"autodel:toggle:title:{chat_id}")],
        [InlineKeyboardButton(f"{anon_status} 匿名管理", callback_data=f"autodel:toggle:anonymous:{chat_id}")],
        # 返回
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]
    return InlineKeyboardMarkup(buttons)
