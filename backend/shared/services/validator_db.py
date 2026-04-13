from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def validate_unique(
    session: AsyncSession,
    model: type,
    filters: dict[str, Any],
    field_name: str = "字段",
    exclude_id: int | None = None,
) -> tuple[bool, str | None]:
    stmt = select(model).where(*[
        getattr(model, k) == v for k, v in filters.items()
        if hasattr(model, k)
    ])

    if exclude_id is not None and hasattr(model, "id"):
        stmt = stmt.where(model.id != exclude_id)

    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        values_str = ", ".join(f"{k}={v}" for k, v in filters.items())
        return False, f"{field_name} ({values_str}) 已存在"

    return True, None


async def validate_exists(
    session: AsyncSession,
    model: type,
    filters: dict[str, Any],
    field_name: str = "记录",
) -> tuple[bool, str | None]:
    stmt = select(model).where(*[
        getattr(model, k) == v for k, v in filters.items()
        if hasattr(model, k)
    ]).limit(1)

    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is None:
        return False, f"{field_name} 不存在"

    return True, None
