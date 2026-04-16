"""管理员相关键盘

包含主菜单、积分配置、自动删除配置、验证等功能。
"""
from backend.features.admin.ui.admin_main import (
    admin_main_menu,
    back_button,
    create_group_selection_keyboard,
    create_guide_keyboard,
    format_admin_main_menu_text,
    format_verification_menu_text,
    toggle_menu,
    verification_mode_menu,
)
from backend.features.admin.ui.auto_delete import auto_delete_config_keyboard
from backend.features.admin.ui.antispam import (
    anti_flood_config_keyboard,
    anti_spam_config_keyboard,
    format_garbage_guard_home_text,
    format_garbage_rule_text,
    garbage_guard_home_keyboard,
    garbage_guard_rule_keyboard,
)
from backend.features.admin.ui.renewal import renewal_entry_keyboard
from backend.features.admin.ui.points import back_button as points_back_button
from backend.features.admin.ui.points import points_config_keyboard

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
    # Renewal
    "renewal_entry_keyboard",
    # Anti flood / anti spam
    "anti_flood_config_keyboard",
    "anti_spam_config_keyboard",
    "format_garbage_guard_home_text",
    "format_garbage_rule_text",
    "garbage_guard_home_keyboard",
    "garbage_guard_rule_keyboard",
]
