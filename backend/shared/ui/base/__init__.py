"""键盘基础构建器和辅助函数

提供统一的键盘构建接口，消除重复代码。
"""
from backend.shared.ui.base.builders import (
    CallbackBuilder,
    KeyboardBuilder,
    PaginatedListBuilder,
)
from backend.shared.ui.base.helpers import (
    create_action_button,
    create_back_button,
    create_confirmation_buttons,
    create_detail_button,
    create_link_button,
    create_menu_buttons,
    create_separator,
    create_toggle_button,
)

__all__ = [
    # Builders
    "CallbackBuilder",
    "KeyboardBuilder",
    "PaginatedListBuilder",
    # Helpers
    "create_back_button",
    "create_confirmation_buttons",
    "create_toggle_button",
    "create_menu_buttons",
    "create_action_button",
    "create_detail_button",
    "create_link_button",
    "create_separator",
]
