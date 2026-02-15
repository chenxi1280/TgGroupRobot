"""管理员相关键盘

包含主菜单、积分配置、自动删除配置、验证等功能。
"""
from bot.keyboards.admin.admin_main import (
    admin_main_menu,
    back_button,
    create_group_selection_keyboard,
    create_guide_keyboard,
    format_admin_main_menu_text,
    format_verification_menu_text,
    toggle_menu,
    verification_mode_menu,
)
from bot.keyboards.admin.auto_delete import auto_delete_config_keyboard
from bot.keyboards.admin.antispam import anti_flood_config_keyboard, anti_spam_config_keyboard
from bot.keyboards.admin.points import back_button as points_back_button
from bot.keyboards.admin.points import points_config_keyboard

__all__ = [
    # Admin main
    "admin_main_menu",
    "back_button",
    "toggle_menu",
    "verification_mode_menu",
    "create_group_selection_keyboard",
    "create_guide_keyboard",
    "format_admin_main_menu_text",
    "format_verification_menu_text",
    # Points
    "points_config_keyboard",
    "points_back_button",
    # Auto delete
    "auto_delete_config_keyboard",
    # Anti flood / anti spam
    "anti_flood_config_keyboard",
    "anti_spam_config_keyboard",
]
