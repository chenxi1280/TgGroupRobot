"""Handler 错误类定义

提供统一的错误类型，用于 Handler 层的错误处理。
"""
from __future__ import annotations


class HandlerError(Exception):
    """Handler 错误基类

    所有 Handler 层的异常都应该继承此类。

    Attributes:
        message: 错误消息
        details: 错误详细信息（可选）
    """

    def __init__(self, message: str, details: str | None = None) -> None:
        """初始化 Handler 错误

        Args:
            message: 错误消息
            details: 错误详细信息（可选）
        """
        self.message = message
        self.details = details
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message


class BusinessRuleError(HandlerError):
    """允许当前流水线记录业务拒绝并继续后续处理器的显式异常。"""


class ChatNotFoundError(HandlerError):
    """群组不存在错误

    当无法找到目标群组时抛出此错误。

    Example:
        >>> raise ChatNotFoundError("未找到指定的群组")
    """

    def __init__(self, message: str = "群组不存在", chat_id: int | None = None) -> None:
        """初始化群组不存在错误

        Args:
            message: 错误消息
            chat_id: 群组 ID（可选）
        """
        details = f"chat_id={chat_id}" if chat_id is not None else None
        super().__init__(message, details)
        self.chat_id = chat_id


class PermissionDeniedError(HandlerError):
    """权限不足错误

    当用户没有执行操作的权限时抛出此错误。

    Example:
        >>> raise PermissionDeniedError("需要管理员权限")
    """

    def __init__(self, message: str = "权限不足", user_id: int | None = None, chat_id: int | None = None) -> None:
        """初始化权限不足错误

        Args:
            message: 错误消息
            user_id: 用户 ID（可选）
            chat_id: 群组 ID（可选）
        """
        details_parts = []
        if user_id is not None:
            details_parts.append(f"user_id={user_id}")
        if chat_id is not None:
            details_parts.append(f"chat_id={chat_id}")

        details = ", ".join(details_parts) if details_parts else None
        super().__init__(message, details)
        self.user_id = user_id
        self.chat_id = chat_id


class InvalidCallbackDataError(HandlerError):
    """无效的 callback_data 错误

    当 callback_data 格式不正确时抛出此错误。

    Example:
        >>> raise InvalidCallbackDataError("callback_data 格式错误")
    """

    def __init__(self, message: str = "无效的回调数据", callback_data: str | None = None) -> None:
        """初始化无效 callback_data 错误

        Args:
            message: 错误消息
            callback_data: 原始 callback_data（可选）
        """
        details = f"data={callback_data}" if callback_data is not None else None
        super().__init__(message, details)
        self.callback_data = callback_data


class ValidationError(HandlerError):
    """参数验证错误

    当输入参数验证失败时抛出此错误。

    Example:
        >>> raise ValidationError("参数验证失败", field="title")
    """

    def __init__(self, message: str = "参数验证失败", field: str | None = None) -> None:
        """初始化参数验证错误

        Args:
            message: 错误消息
            field: 字段名（可选）
        """
        details = f"field={field}" if field is not None else None
        super().__init__(message, details)
        self.field = field


class StateNotFoundError(HandlerError):
    """状态不存在错误

    当用户状态不存在时抛出此错误。

    Example:
        >>> raise StateNotFoundError("用户状态不存在")
    """

    def __init__(self, message: str = "用户状态不存在", state_type: str | None = None) -> None:
        """初始化状态不存在错误

        Args:
            message: 错误消息
            state_type: 状态类型（可选）
        """
        details = f"state_type={state_type}" if state_type is not None else None
        super().__init__(message, details)
        self.state_type = state_type
