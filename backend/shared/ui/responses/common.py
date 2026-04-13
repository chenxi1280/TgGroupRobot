"""通用响应格式化类

提供通用的消息格式化方法。
"""
from __future__ import annotations


class CommonResponse:
    """通用响应格式化类

    提供通用的消息格式化方法，如成功、错误、提示等。
    """

    @staticmethod
    def success(message: str) -> str:
        """格式化成功消息

        Args:
            message: 成功消息内容

        Returns:
            str: 格式化后的成功消息
        """
        return f"✅ {message}"

    @staticmethod
    def error(message: str) -> str:
        """格式化错误消息

        Args:
            message: 错误消息内容

        Returns:
            str: 格式化后的错误消息
        """
        return f"❌ {message}"

    @staticmethod
    def warning(message: str) -> str:
        """格式化警告消息

        Args:
            message: 警告消息内容

        Returns:
            str: 格式化后的警告消息
        """
        return f"⚠️ {message}"

    @staticmethod
    def info(message: str) -> str:
        """格式化信息消息

        Args:
            message: 信息内容

        Returns:
            str: 格式化后的信息消息
        """
        return f"ℹ️ {message}"

    @staticmethod
    def loading(message: str = "处理中...") -> str:
        """格式化加载中消息

        Args:
            message: 加载消息内容

        Returns:
            str: 格式化后的加载中消息
        """
        return f"⏳ {message}"

    @staticmethod
    def permission_denied() -> str:
        """格式化权限拒绝消息

        Returns:
            str: 格式化后的权限拒绝消息
        """
        return "❌ 需要管理员权限才能执行此操作。"

    @staticmethod
    def not_found(resource: str = "资源") -> str:
        """格式化未找到消息

        Args:
            resource: 资源名称

        Returns:
            str: 格式化后的未找到消息
        """
        return f"❌ {resource}不存在。"

    @staticmethod
    def operation_failed(reason: str = "") -> str:
        """格式化操作失败消息

        Args:
            reason: 失败原因（可选）

        Returns:
            str: 格式化后的操作失败消息
        """
        if reason:
            return f"❌ 操作失败：{reason}"
        return "❌ 操作失败"

    @staticmethod
    def cancelled() -> str:
        """格式化操作取消消息

        Returns:
            str: 格式化后的操作取消消息
        """
        return "✅ 操作已取消"

    @staticmethod
    def confirm_prompt(action: str) -> str:
        """格式化确认提示

        Args:
            action: 要确认的操作描述

        Returns:
            str: 格式化后的确认提示
        """
        return f"⚠️ 确认要{action}吗？"

    @staticmethod
    def format_list(items: list[str], title: str = "") -> str:
        """格式化列表

        Args:
            items: 列表项
            title: 列表标题（可选）

        Returns:
            str: 格式化后的列表
        """
        if not items:
            return "暂无数据"

        text = f"{title}\n\n" if title else ""
        for i, item in enumerate(items, 1):
            text += f"{i}. {item}\n"
        return text

    @staticmethod
    def format_stats(stats: dict[str, int | str], title: str = "📊 统计") -> str:
        """格式化统计数据

        Args:
            stats: 统计数据字典
            title: 统计标题

        Returns:
            str: 格式化后的统计数据
        """
        text = f"{title}\n\n"
        for key, value in stats.items():
            text += f"{key}: {value}\n"
        return text
