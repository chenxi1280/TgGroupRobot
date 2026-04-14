"""管理员主菜单键盘

提供管理员主菜单、验证模式选择等功能。
"""
from __future__ import annotations

from backend.features.admin.ui.admin_main_keyboards import (
    admin_main_menu,
    back_button,
    create_group_selection_keyboard,
    create_guide_keyboard,
    toggle_menu,
)
from backend.features.admin.ui.admin_main_text import (
    format_admin_main_menu_text,
    format_verification_menu_text,
)
from backend.features.admin.ui.admin_verification_keyboards import (
    verification_config_menu,
    verification_mode_menu,
    verification_timeout_action_menu,
)

