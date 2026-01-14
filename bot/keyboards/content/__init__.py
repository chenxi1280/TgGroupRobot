"""内容管理键盘

包含广告、自动回复、违禁词管理等功能。
"""
from bot.keyboards.content.ads import (
    ads_create_keyboard,
    ads_detail_keyboard,
    ads_frequency_keyboard,
    ads_list_keyboard,
    ads_menu_keyboard,
)
from bot.keyboards.content.auto_reply import (
    auto_reply_list_keyboard,
    auto_reply_menu_keyboard,
)
from bot.keyboards.content.banned_word import (
    banned_word_list_keyboard,
    banned_word_menu_keyboard,
)

__all__ = [
    # Ads
    "ads_menu_keyboard",
    "ads_list_keyboard",
    "ads_detail_keyboard",
    "ads_create_keyboard",
    "ads_frequency_keyboard",
    # Auto reply
    "auto_reply_menu_keyboard",
    "auto_reply_list_keyboard",
    # Banned word
    "banned_word_menu_keyboard",
    "banned_word_list_keyboard",
]
