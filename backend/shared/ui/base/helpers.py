"""键盘辅助函数

提供常用的按钮创建辅助函数，消除重复代码。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton

from backend.shared.ui.base.builders import CallbackBuilder


def create_back_button(
    chat_id: int | None,
    to_menu: str = "main",
    label: str = "🔙 返回",
    prefix: str = "adm",
) -> InlineKeyboardButton:
    """创建返回按钮

    Args:
        chat_id: 群组 ID，用于私聊管理场景
        to_menu: 返回到的菜单名称
        label: 按钮标签
        prefix: 回调前缀

    Returns:
        InlineKeyboardButton 对象

    Example:
        >>> btn = create_back_button(123, "main", "🔙 返回")
        >>> btn.callback_data
        'adm:menu:123:main'
    """
    callback_builder = CallbackBuilder(prefix, chat_id)
    callback_data = callback_builder.build("menu", to_menu)
    return InlineKeyboardButton(label, callback_data=callback_data)


def create_confirmation_buttons(
    confirm_callback: str,
    cancel_callback: str,
    confirm_label: str = "✅ 确认",
    cancel_label: str = "❌ 取消",
) -> list[InlineKeyboardButton]:
    """创建确认对话框按钮

    Args:
        confirm_callback: 确认按钮的回调数据
        cancel_callback: 取消按钮的回调数据
        confirm_label: 确认按钮标签
        cancel_label: 取消按钮标签

    Returns:
        包含两个按钮的列表

    Example:
        >>> buttons = create_confirmation_buttons("confirm:123", "cancel:123")
        >>> len(buttons)
        2
    """
    return [
        InlineKeyboardButton(confirm_label, callback_data=confirm_callback),
        InlineKeyboardButton(cancel_label, callback_data=cancel_callback),
    ]


def create_toggle_button(
    label: str,
    key: str,
    enabled: bool,
    prefix: str = "toggle",
    chat_id: int | None = None,
) -> InlineKeyboardButton:
    """创建开关按钮

    Args:
        label: 按钮标签
        key: 开关标识
        enabled: 是否启用
        prefix: 回调前缀
        chat_id: 群组 ID

    Returns:
        InlineKeyboardButton 对象

    Example:
        >>> btn = create_toggle_button("自动回复", "auto_reply", True, "arp", 123)
        >>> btn.callback_data
        'arp:toggle:123:auto_reply'
    """
    callback_builder = CallbackBuilder(prefix, chat_id)
    callback_data = callback_builder.build("toggle", key)

    # 添加状态图标
    icon = "🟢" if enabled else "🔴"
    return InlineKeyboardButton(f"{icon} {label}", callback_data=callback_data)


def create_menu_buttons(
    menu_items: list[tuple[str, str]],
    prefix: str,
    chat_id: int | None = None,
) -> list[InlineKeyboardButton]:
    """批量创建菜单按钮

    Args:
        menu_items: 菜单项列表，每项为 (标签, 动作) 元组
        prefix: 回调前缀
        chat_id: 群组 ID

    Returns:
        InlineKeyboardButton 对象列表

    Example:
        >>> items = [("创建", "create"), ("列表", "list")]
        >>> buttons = create_menu_buttons(items, "lot", 123)
        >>> len(buttons)
        2
    """
    callback_builder = CallbackBuilder(prefix, chat_id)
    buttons = []

    for label, action in menu_items:
        callback_data = callback_builder.build("menu", action)
        buttons.append(InlineKeyboardButton(label, callback_data=callback_data))

    return buttons


def create_action_button(
    label: str,
    action: str,
    prefix: str,
    chat_id: int | None = None,
    *args: int | str,
) -> InlineKeyboardButton:
    """创建动作按钮

    Args:
        label: 按钮标签
        action: 动作名称
        prefix: 回调前缀
        chat_id: 群组 ID
        *args: 额外的动作参数

    Returns:
        InlineKeyboardButton 对象

    Example:
        >>> btn = create_action_button("编辑", "edit", "arp", 123, 1)
        >>> btn.callback_data
        'arp:edit:123:1'
    """
    callback_builder = CallbackBuilder(prefix, chat_id)
    callback_data = callback_builder.build(action, *args)
    return InlineKeyboardButton(label, callback_data=callback_data)


def create_detail_button(
    label: str,
    item_id: int,
    prefix: str,
    chat_id: int | None = None,
    action: str = "detail",
) -> InlineKeyboardButton:
    """创建详情按钮

    Args:
        label: 按钮标签
        item_id: 项目 ID
        prefix: 回调前缀
        chat_id: 群组 ID
        action: 动作名称，默认为 "detail"

    Returns:
        InlineKeyboardButton 对象

    Example:
        >>> btn = create_detail_button("查看", 5, "lot", 123)
        >>> btn.callback_data
        'lot:detail:123:5'
    """
    callback_builder = CallbackBuilder(prefix, chat_id)
    callback_data = callback_builder.build(action, item_id)
    return InlineKeyboardButton(label, callback_data=callback_data)


def create_link_button(
    label: str,
    url: str,
) -> InlineKeyboardButton:
    """创建链接按钮

    Args:
        label: 按钮标签
        url: 链接地址

    Returns:
        InlineKeyboardButton 对象

    Example:
        >>> btn = create_link_button("访问网站", "https://example.com")
        >>> btn.url
        'https://example.com'
    """
    return InlineKeyboardButton(label, url=url)


def create_separator(
    text: str = "━" * 15,
    callback: str = "_",
) -> InlineKeyboardButton:
    """创建分隔线按钮

    Args:
        text: 分隔线文本
        callback: 回调数据（通常为无效值）

    Returns:
        InlineKeyboardButton 对象

    Example:
        >>> btn = create_separator("━" * 15)
        >>> btn.callback_data
        '_'
    """
    return InlineKeyboardButton(text, callback_data=callback)
