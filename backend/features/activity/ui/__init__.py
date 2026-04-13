"""活动相关键盘

包含抽奖、接龙等功能。
"""
from backend.features.activity.ui.lottery import (
    get_join_keyboard,
    lottery_menu_keyboard,
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)
from backend.features.activity.ui.solitaire import (
    get_join_solitaire_keyboard,
    solitaire_create_keyboard,
    solitaire_detail_keyboard,
    solitaire_list_keyboard,
    solitaire_menu_keyboard,
)

__all__ = [
    # Lottery
    "lottery_menu_keyboard",
    "manual_draw_prize_keyboard",
    "manual_draw_summary_keyboard",
    "manual_draw_summary_keyboard_with_winners",
    "get_join_keyboard",
    # Solitaire
    "solitaire_menu_keyboard",
    "solitaire_list_keyboard",
    "solitaire_detail_keyboard",
    "solitaire_create_keyboard",
    "get_join_solitaire_keyboard",
]
