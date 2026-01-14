from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import TypeVar, Generic

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar('T')


@dataclass
class ServiceResult(Generic[T]):
    """统一的服务返回结果"""
    success: bool
    data: T | None = None
    error: str | None = None


class ServiceError(Exception):
    """服务层异常基类"""
    pass


class ValidationError(ServiceError):
    """验证错误"""
    pass


class PermissionError(ServiceError):
    """权限错误"""
    pass


class NotFoundError(ServiceError):
    """资源未找到"""
    pass


class BaseService(ABC):
    """服务基类，提供通用功能"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
