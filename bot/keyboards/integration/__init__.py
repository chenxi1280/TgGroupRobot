"""集成功能键盘

包含邀请链接等功能。
"""
from bot.keyboards.integration.invite_link import (
    invite_link_create_keyboard,
    invite_link_detail_keyboard,
    invite_link_list_keyboard,
    invite_link_menu_keyboard,
    user_invite_menu_keyboard,
)

__all__ = [
    # Invite link
    "invite_link_menu_keyboard",
    "invite_link_list_keyboard",
    "invite_link_detail_keyboard",
    "invite_link_create_keyboard",
    "user_invite_menu_keyboard",
]
