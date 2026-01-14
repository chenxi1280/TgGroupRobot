from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any, TypeVar, Generic

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta

from bot.services.shared.result import CreateResult

T = TypeVar('T')
ModelT = TypeVar('ModelT', bound=DeclarativeMeta)


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


class ServiceBase:
    """
    服务基类，提供通用的数据库操作方法

    子类继承后可以直接使用这些方法，避免重复代码。

    示例:
        class MyService(ServiceBase):
            async def create_item(self, session, data):
                return await self._create_entity(session, Item(**data))
    """

    @staticmethod
    async def _create_entity(session: AsyncSession, entity: Any) -> CreateResult:
        """
        通用的实体创建方法

        将实体添加到会话并刷新，使其获得数据库生成的ID。

        Args:
            session: 异步数据库会话
            entity: 要创建的实体实例

        Returns:
            CreateResult: 包含创建结果的返回对象
        """
        session.add(entity)
        await session.flush()
        return CreateResult(
            success=True,
            reason="ok",
            entity=entity,
            entity_id=getattr(entity, 'id', None),
        )

    @staticmethod
    async def _get_by_id(
        session: AsyncSession,
        model: type[ModelT],
        entity_id: int
    ) -> ModelT | None:
        """
        通用的根据ID获取实体方法

        Args:
            session: 异步数据库会话
            model: 模型类
            entity_id: 实体ID

        Returns:
            实体对象，如果不存在则返回 None
        """
        stmt = select(model).where(model.id == entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def _get_list(
        session: AsyncSession,
        model: type[ModelT],
        filters: dict[str, Any] | None = None,
        active_only: bool = False,
        order_by: str = "created_at",
        descending: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ModelT]:
        """
        通用的获取列表方法

        Args:
            session: 异步数据库会话
            model: 模型类
            filters: 过滤条件字典，格式为 {字段名: 值}
            active_only: 是否只返回激活状态的实体（需要模型有 is_active 字段）
            order_by: 排序字段名
            descending: 是否降序排列
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            实体列表
        """
        stmt = select(model)

        if filters:
            for key, value in filters.items():
                if hasattr(model, key):
                    stmt = stmt.where(getattr(model, key) == value)

        if active_only and hasattr(model, 'is_active'):
            stmt = stmt.where(model.is_active == True)

        order_col = getattr(model, order_by, None)
        if order_col is not None:
            if descending:
                stmt = stmt.order_by(order_col.desc())
            else:
                stmt = stmt.order_by(order_col)

        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def _count(
        session: AsyncSession,
        model: type[ModelT],
        filters: dict[str, Any] | None = None,
    ) -> int:
        """
        通用的计数方法

        Args:
            session: 异步数据库会话
            model: 模型类
            filters: 过滤条件字典

        Returns:
            符合条件的记录数量
        """
        stmt = select(func.count(model.id))

        if filters:
            for key, value in filters.items():
                if hasattr(model, key):
                    stmt = stmt.where(getattr(model, key) == value)

        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def _get_by_filters(
        session: AsyncSession,
        model: type[ModelT],
        filters: dict[str, Any],
    ) -> ModelT | None:
        """
        通用的根据过滤条件获取单个实体方法

        Args:
            session: 异步数据库会话
            model: 模型类
            filters: 过滤条件字典

        Returns:
            实体对象，如果不存在则返回 None
        """
        stmt = select(model)
        for key, value in filters.items():
            if hasattr(model, key):
                stmt = stmt.where(getattr(model, key) == value)

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def _delete_entity(session: AsyncSession, entity: Any) -> bool:
        """
        通用的删除实体方法

        Args:
            session: 异步数据库会话
            entity: 要删除的实体实例

        Returns:
            True 表示删除成功
        """
        await session.delete(entity)
        await session.flush()
        return True

    @staticmethod
    async def _upsert_entity(
        session: AsyncSession,
        model: type[ModelT],
        filters: dict[str, Any],
        updates: dict[str, Any],
    ) -> ModelT:
        """
        通用的替换或创建方法（update or insert）

        如果根据 filters 找到现有记录，则删除并创建新记录；
        如果找不到，则直接创建新记录。

        Args:
            session: 异步数据库会话
            model: 模型类
            filters: 用于查找现有记录的过滤条件
            updates: 用于创建/更新记录的数据

        Returns:
            新创建的实体对象
        """
        stmt = select(model).where(*[
            getattr(model, k) == v for k, v in filters.items()
            if hasattr(model, k)
        ])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            await session.delete(existing)
            await session.flush()

        new_entity = model(**updates)
        session.add(new_entity)
        await session.flush()
        return new_entity

    @staticmethod
    async def _update_entity(
        session: AsyncSession,
        entity: Any,
        updates: dict[str, Any],
    ) -> Any:
        """
        通用的更新实体方法

        Args:
            session: 异步数据库会话
            entity: 要更新的实体实例
            updates: 更新数据字典

        Returns:
            更新后的实体对象
        """
        for key, value in updates.items():
            if hasattr(entity, key):
                setattr(entity, key, value)

        await session.flush()
        return entity

    @staticmethod
    async def _exists(
        session: AsyncSession,
        model: type[ModelT],
        filters: dict[str, Any],
    ) -> bool:
        """
        通用的存在性检查方法

        Args:
            session: 异步数据库会话
            model: 模型类
            filters: 过滤条件字典

        Returns:
            True 如果存在符合条件的记录，否则返回 False
        """
        stmt = select(model.id).where(*[
            getattr(model, k) == v for k, v in filters.items()
            if hasattr(model, k)
        ]).limit(1)

        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None
