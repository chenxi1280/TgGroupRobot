"""键盘构建器基类和通用构建器

提供统一的键盘构建接口，消除重复代码。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

T = TypeVar("T")


@dataclass
class CallbackBuilder:
    """回调数据构建器

    统一管理回调数据的格式，避免在每个键盘函数中重复拼接字符串。

    Attributes:
        prefix: 回调前缀，如 'adm'、'lot'
        chat_id: 群组 ID，用于私聊管理场景
    """

    prefix: str
    """回调前缀，如 'adm'、'lot'"""

    chat_id: int | None = None
    """群组 ID，用于私聊管理场景"""

    def build(self, action: str, *args, **kwargs) -> str:
        """构建回调数据

        Args:
            action: 动作名称，如 'menu'、'create'
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            格式化的回调数据字符串

        Example:
            >>> builder = CallbackBuilder("lot", chat_id=123)
            >>> builder.build("create", 1, 2)
            'lot:create:123:1:2'
        """
        parts = [self.prefix, action]

        # 如果有 chat_id，作为第一个参数插入
        if self.chat_id is not None:
            parts.append(str(self.chat_id))

        # 添加位置参数
        parts.extend(str(arg) for arg in args)

        # 添加关键字参数（可选）
        for key, value in kwargs.items():
            parts.append(f"{key}={value}")

        return ":".join(parts)


class KeyboardBuilder:
    """键盘构建器基类

    提供链式 API 来构建 InlineKeyboardMarkup。

    Example:
        >>> builder = KeyboardBuilder("lot", chat_id=123)
        >>> keyboard = (builder
        ...              .add_button("创建抽奖", "create")
        ...              .add_back_button()
        ...              .build())
    """

    def __init__(self, callback_prefix: str, chat_id: int | None = None):
        """初始化构建器

        Args:
            callback_prefix: 回调数据前缀
            chat_id: 群组 ID，用于私聊管理场景
        """
        self.callback_prefix = callback_prefix
        self.chat_id = chat_id
        self.callback_builder = CallbackBuilder(callback_prefix, chat_id)
        self._buttons: list[list[InlineKeyboardButton]] = []

    def add_row(self, *buttons: InlineKeyboardButton) -> "KeyboardBuilder":
        """添加一行按钮

        Args:
            *buttons: 一个或多个 InlineKeyboardButton

        Returns:
            self, 支持链式调用

        Example:
            >>> builder.add_row(
            ...     InlineKeyboardButton("A", callback_data="a"),
            ...     InlineKeyboardButton("B", callback_data="b")
            ... )
        """
        self._buttons.append(list(buttons))
        return self

    def add_button(
        self,
        label: str,
        action: str,
        *args: Any,
    ) -> "KeyboardBuilder":
        """添加一个按钮（新行）

        Args:
            label: 按钮标签
            action: 动作名称
            *args: 动作参数

        Returns:
            self, 支持链式调用

        Example:
            >>> builder.add_button("创建", "create", 1)
        """
        callback_data = self.callback_builder.build(action, *args)
        self._buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])
        return self

    def add_back_button(
        self,
        to_menu: str = "main",
        label: str = "🔙 返回",
    ) -> "KeyboardBuilder":
        """添加返回按钮

        Args:
            to_menu: 返回到的菜单名称
            label: 按钮标签

        Returns:
            self, 支持链式调用
        """
        return self.add_button(label, "menu", to_menu)

    def add_separator(
        self,
        text: str = "━" * 15,
        callback: str = "separator",
    ) -> "KeyboardBuilder":
        """添加分隔线

        Args:
            text: 分隔线文本
            callback: 回调数据

        Returns:
            self, 支持链式调用
        """
        self._buttons.append([
            InlineKeyboardButton(text, callback_data=f"{self.callback_prefix}:{callback}")
        ])
        return self

    def add_pagination(
        self,
        current_page: int,
        total_items: int,
        page_size: int,
        list_action: str = "list",
    ) -> "KeyboardBuilder":
        """添加分页导航

        Args:
            current_page: 当前页码（从 0 开始）
            total_items: 总项目数
            page_size: 每页大小
            list_action: 列表动作名称

        Returns:
            self, 支持链式调用
        """
        total_pages = (total_items + page_size - 1) // page_size

        if total_pages <= 1:
            return self

        nav_buttons = []

        # 上一页
        if current_page > 0:
            prev_callback = self.callback_builder.build(list_action, current_page - 1)
            nav_buttons.append(
                InlineKeyboardButton("⬅️ 上一页", callback_data=prev_callback)
            )

        # 下一页
        if current_page < total_pages - 1:
            next_callback = self.callback_builder.build(list_action, current_page + 1)
            nav_buttons.append(
                InlineKeyboardButton("下一页 ➡️", callback_data=next_callback)
            )

        if nav_buttons:
            self._buttons.append(nav_buttons)

        return self

    def build(self) -> InlineKeyboardMarkup:
        """构建键盘

        Returns:
            InlineKeyboardMarkup 对象
        """
        return InlineKeyboardMarkup(self._buttons)

    def reset(self) -> "KeyboardBuilder":
        """重置构建器

        清空所有已添加的按钮，准备构建新的键盘。

        Returns:
            self, 支持链式调用
        """
        self._buttons = []
        return self


class PaginatedListBuilder(KeyboardBuilder, Generic[T]):
    """分页列表构建器

    用于构建带有分页功能的列表键盘。

    Type Args:
        T: 列表项类型

    Example:
        >>> def format_user(user):
        ...     return user.name
        >>> builder = PaginatedListBuilder("users", format_user, "detail")
        >>> builder.add_items(users, page=0, page_size=10)
    """

    def __init__(
        self,
        callback_prefix: str,
        item_formatter: Callable[[T], str],
        item_action: str = "detail",
        chat_id: int | None = None,
    ):
        """初始化分页列表构建器

        Args:
            callback_prefix: 回调前缀
            item_formatter: 项目格式化函数 (item) -> label
            item_action: 点击项目时的动作
            chat_id: 群组 ID
        """
        super().__init__(callback_prefix, chat_id)
        self.item_formatter = item_formatter
        self.item_action = item_action

    def add_items(
        self,
        items: list[T],
        page: int = 0,
        page_size: int = 5,
        get_item_id: Callable[[T], int] | None = None,
    ) -> "PaginatedListBuilder[T]":
        """添加分页项目

        Args:
            items: 项目列表
            page: 当前页码
            page_size: 每页大小
            get_item_id: 获取项目 ID 的函数

        Returns:
            self, 支持链式调用
        """
        start_idx = page * page_size
        end_idx = start_idx + page_size

        for item in items[start_idx:end_idx]:
            label = self.item_formatter(item)

            if get_item_id:
                item_id = get_item_id(item)
                self.add_button(label, self.item_action, item_id)
            else:
                self.add_button(label, self.item_action)

        # 添加分页导航
        self.add_pagination(page, len(items), page_size, "list")

        return self
