"""状态图标映射

统一管理各种状态的图标表示，消除重复的状态图标代码。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StatusIconSet:
    """状态图标集

    定义一组状态对应的图标映射。

    Attributes:
        active: 启用/激活状态图标
        inactive: 未启用/未激活状态图标
        disabled: 禁用状态图标
        pending: 待处理状态图标
        success: 成功状态图标
        error: 错误状态图标
        warning: 警告状态图标
        unknown: 未知状态图标
    """

    active: str = "🟢"
    inactive: str = "🔴"
    disabled: str = "⚪"
    pending: str = "🟡"
    success: str = "✅"
    error: str = "❌"
    warning: str = "⚠️"
    unknown: str = "❓"

    def get(self, status: str | int, default: str | None = None) -> str | None:
        """根据状态获取图标

        Args:
            status: 状态值（字符串或整数）
            default: 默认图标，默认为 unknown

        Returns:
            对应的状态图标
        """
        if default is None:
            default = self.unknown

        # 支持字符串状态
        status_map = {
            "active": self.active,
            "enabled": self.active,
            "open": self.active,
            "on": self.active,
            "true": self.active,
            "1": self.active,
            True: self.active,
            1: self.active,
            "inactive": self.inactive,
            "disabled": self.inactive,
            "closed": self.inactive,
            "off": self.inactive,
            "false": self.inactive,
            "0": self.inactive,
            False: self.inactive,
            0: self.inactive,
            "pending": self.pending,
            "waiting": self.pending,
            "success": self.success,
            "completed": self.success,
            "done": self.success,
            "error": self.error,
            "failed": self.error,
            "warning": self.warning,
        }

        return status_map.get(status, default)


class StatusIcons:
    """状态图标工具类

    提供静态方法获取各种状态图标，避免在各个键盘文件中重复定义。

    Example:
        >>> icon = StatusIcons.enabled(True)  # "🟢"
        >>> icon = StatusIcons.active("active")  # "🟢"
        >>> icon_set = StatusIcons.for_ads()
        >>> icon = icon_set.get("enabled")  # "🟢"
    """

    # 默认图标集
    DEFAULT = StatusIconSet()

    # 启用/禁用状态
    @staticmethod
    def enabled(is_enabled: bool) -> str:
        """获取启用状态图标

        Args:
            is_enabled: 是否启用

        Returns:
            状态图标
        """
        return StatusIcons.DEFAULT.active if is_enabled else StatusIcons.DEFAULT.inactive

    @staticmethod
    def active(is_active: bool) -> str:
        """获取激活状态图标

        Args:
            is_active: 是否激活

        Returns:
            状态图标
        """
        return StatusIcons.DEFAULT.active if is_active else StatusIcons.DEFAULT.inactive

    @staticmethod
    def open(is_open: bool) -> str:
        """获取开放状态图标

        Args:
            is_open: 是否开放

        Returns:
            状态图标
        """
        return StatusIcons.DEFAULT.active if is_open else StatusIcons.DEFAULT.inactive

    # 布尔状态
    @staticmethod
    def boolean(value: bool, true_icon: str = "✅", false_icon: str = "❌") -> str:
        """获取布尔状态图标

        Args:
            value: 布尔值
            true_icon: 真值图标
            false_icon: 假值图标

        Returns:
            状态图标
        """
        return true_icon if value else false_icon

    # 特定领域的图标集

    @staticmethod
    def for_ads() -> StatusIconSet:
        """广告管理状态图标集"""
        return StatusIconSet(
            active="🟢",
            inactive="🔴",
        )

    @staticmethod
    def for_invite_links() -> StatusIconSet:
        """邀请链接状态图标集"""
        return StatusIconSet(
            active="🟢",
            inactive="🔴",
            disabled="⚪",
        )

    @staticmethod
    def for_solitaire() -> StatusIconSet:
        """接龙状态图标集"""
        return StatusIconSet(
            active="🟢",
            inactive="🔴",
            disabled="⚪",
        )

    @staticmethod
    def for_auto_reply() -> StatusIconSet:
        """自动回复状态图标集"""
        return StatusIconSet(
            active="🟢",
            inactive="🔴",
        )

    @staticmethod
    def for_banned_word() -> StatusIconSet:
        """违禁词状态图标集"""
        return StatusIconSet(
            active="🟢",
            inactive="🔴",
        )

    @staticmethod
    def for_scheduled() -> StatusIconSet:
        """定时消息状态图标集"""
        return StatusIconSet(
            active="🟢",
            inactive="🔴",
        )

    @staticmethod
    def for_lottery() -> StatusIconSet:
        """抽奖状态图标集"""
        return StatusIconSet(
            active="🟢",
            inactive="🔴",
            pending="🟡",
        )

    # 通用图标获取

    @staticmethod
    def from_value(
        value: Any,
        true_value: Any = True,
        active_icon: str = "🟢",
        *, inactive_icon: str = "🔴",
    ) -> str:
        """根据值获取状态图标

        Args:
            value: 状态值
            true_value: 判断为真的值
            active_icon: 激活图标
            inactive_icon: 未激活图标

        Returns:
            状态图标
        """
        return active_icon if value == true_value else inactive_icon

    @staticmethod
    def from_mapping(
        value: Any,
        mapping: dict[Any, str],
        default: str = "❓",
    ) -> str:
        """从自定义映射获取状态图标

        Args:
            value: 状态值
            mapping: 状态值到图标的映射
            default: 默认图标

        Returns:
            状态图标
        """
        return mapping.get(value, default)


# 常用图标常量（向后兼容）
class Icon:
    """常用图标常量

    提供常用的图标常量，方便直接使用。
    """

    # 状态图标
    ACTIVE = "🟢"
    INACTIVE = "🔴"
    DISABLED = "⚪"
    PENDING = "🟡"

    # 结果图标
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"

    # 导航图标
    BACK = "🔙"
    FORWARD = "➡️"
    HOME = "🏠"
    MENU = "📋"

    # 操作图标
    ADD = "➕"
    EDIT = "✏️"
    DELETE = "🗑️"
    COPY = "📋"
    SHARE = "📤"

    # 功能图标
    SETTINGS = "⚙️"
    SEARCH = "🔍"
    FILTER = "🔬"
    SORT = "🔃"
