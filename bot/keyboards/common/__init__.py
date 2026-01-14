"""通用键盘

包含群组选择、开始引导、验证按钮等通用功能。
"""
from bot.keyboards.common.chat_group import chat_group_list_keyboard
from bot.keyboards.common.start import create_start_guide_keyboard
from bot.keyboards.common.verification import verification_keyboard

__all__ = [
    "verification_keyboard",
    "create_start_guide_keyboard",
    "chat_group_list_keyboard",
]
