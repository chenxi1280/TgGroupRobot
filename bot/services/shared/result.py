"""统一结果对象定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class ServiceResult:
    """
    统一服务结果对象

    用于封装服务操作的执行结果，提供统一的返回格式
    """

    success: bool
    """操作是否成功"""

    reason: str
    """操作结果的原因或状态描述"""

    data: Any = None
    """操作返回的数据（可选）"""

    error: str | None = None
    """错误信息（如果操作失败）"""

    def __bool__(self) -> bool:
        """允许将结果对象直接用于布尔判断"""
        return self.success


@dataclass
class OperationResult(ServiceResult, Generic[T]):
    """
    泛型操作结果对象

    用于需要指定具体返回类型的服务操作
    """

    data: T | None = None
    """操作返回的强类型数据"""

    @classmethod
    def ok(cls, reason: str = "ok", data: T | None = None) -> "OperationResult[T]":
        """创建成功结果"""
        return cls(success=True, reason=reason, data=data)

    @classmethod
    def failed(cls, reason: str, error: str | None = None) -> "OperationResult[T]":
        """创建失败结果"""
        return cls(success=False, reason=reason, error=error)


@dataclass
class CreateResult(ServiceResult):
    """
    创建操作结果

    用于创建资源的操作，返回创建的对象和相关信息
    """

    entity: Any = None
    """创建的实体对象"""

    entity_id: int | None = None
    """创建的实体ID"""

    message_id: int | None = None
    """关联的消息ID（如Telegram消息ID）"""


@dataclass
class JoinResult(ServiceResult):
    """
    参与操作结果

    用于用户参与活动（如抽奖、接龙）的操作
    """

    entity: Any = None
    """参与的目标实体"""


@dataclass
class CloseResult(ServiceResult):
    """
    关闭操作结果

    用于关闭活动（如接龙、抽奖）的操作
    """

    entity: Any = None
    """被关闭的实体对象"""


@dataclass
class MatchResult(ServiceResult):
    """
    匹配操作结果

    用于内容匹配操作（如自动回复、违禁词检测）
    """

    rule: Any = None
    """匹配的规则"""

    reply_content: str | None = None
    """回复内容"""


@dataclass
class ToggleResult(ServiceResult):
    """
    切换操作结果

    用于切换状态（如启用/禁用）
    """

    entity: Any = None
    """被切换的实体"""


@dataclass
class UpdateResult(ServiceResult):
    """
    更新操作结果

    用于更新资源的操作
    """

    entity: Any = None
    """更新后的实体对象"""
