"""回调数据解析工具类

提供统一的回调数据解析接口，减少重复的解析代码。
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


class CallbackData:
    """回调数据封装类

    提供类型安全的回调数据访问。
    """

    def __init__(self, raw_data: str, parts: list[str]) -> None:
        """初始化回调数据

        Args:
            raw_data: 原始回调数据
            parts: 解析后的数据部分
        """
        self.raw_data = raw_data
        self._parts = parts

    @property
    def action(self) -> str:
        """获取操作类型（第一部分）

        Returns:
            str: 操作类型
        """
        return self._parts[0] if self._parts else ""

    @property
    def parts(self) -> list[str]:
        """获取所有数据部分

        Returns:
            list[str]: 数据部分列表
        """
        return self._parts

    def get(self, index: int, default: str = "") -> str:
        """获取指定索引的数据部分

        Args:
            index: 索引（从 0 开始）
            default: 默认值

        Returns:
            str: 数据部分或默认值
        """
        if 0 <= index < len(self._parts):
            return self._parts[index]
        return default

    def get_int(self, index: int, default: int = 0) -> int:
        """获取指定索引的数据部分（转换为整数）

        Args:
            index: 索引（从 0 开始）
            default: 默认值

        Returns:
            int: 整数值或默认值
        """
        if 0 <= index < len(self._parts):
            try:
                return int(self._parts[index])
            except ValueError:
                log.warning("invalid_int_in_callback", index=index, value=self._parts[index])
                return default
        return default

    def length(self) -> int:
        """获取数据部分数量

        Returns:
            int: 数据部分数量
        """
        return len(self._parts)

    def __str__(self) -> str:
        return self.raw_data

    def __repr__(self) -> str:
        return f"CallbackData(raw='{self.raw_data}', parts={self._parts})"


class CallbackParser:
    """回调数据解析器

    提供统一的回调数据解析方法。
    """

    @staticmethod
    def parse(data: str, separator: str = ":", expected_parts: int = 0) -> CallbackData:
        """解析回调数据

        Args:
            data: 回调数据字符串
            separator: 分隔符（默认 ":"）
            expected_parts: 期望的数据部分数量（0 表示不限制）

        Returns:
            CallbackData: 解析后的回调数据对象
        """
        parts = data.split(separator)

        if expected_parts > 0 and len(parts) < expected_parts:
            log.warning(
                "callback_data_parts_mismatch",
                data=data,
                expected=expected_parts,
                actual=len(parts),
            )

        return CallbackData(data, parts)

    @staticmethod
    def parse_action_only(data: str) -> str:
        """只解析操作类型（第一部分）

        Args:
            data: 回调数据字符串

        Returns:
            str: 操作类型
        """
        return data.split(":")[0] if data else ""

    @staticmethod
    def parse_id(data: str, index: int = 1) -> int | None:
        """解析 ID（常用于解析第二部分的整数 ID）

        Args:
            data: 回调数据字符串
            index: ID 所在的索引（默认 1）

        Returns:
            int | None: 解析出的 ID，失败返回 None
        """
        parts = data.split(":")
        if index < len(parts):
            try:
                return int(parts[index])
            except ValueError:
                log.warning("invalid_id_in_callback", data=data, index=index)
                return None
        return None

    @staticmethod
    def build(action: str, *parts: int | str, separator: str = ":") -> str:
        """构建回调数据

        Args:
            action: 操作类型
            *parts: 数据部分
            separator: 分隔符（默认 ":"）

        Returns:
            str: 构建好的回调数据字符串
        """
        parts_str = [str(p) for p in parts]
        return separator.join([action, *parts_str])

    @staticmethod
    def validate_action(data: str, expected_action: str) -> bool:
        """验证操作类型

        Args:
            data: 回调数据字符串
            expected_action: 期望的操作类型

        Returns:
            bool: 操作类型是否匹配
        """
        action = CallbackParser.parse_action_only(data)
        return action == expected_action
