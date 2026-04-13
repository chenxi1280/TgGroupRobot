from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.platform.db.schema.models.core import Solitaire
from backend.platform.db.schema.models.enums import SolitaireStatus
from backend.shared.services.base import ServiceBase


async def get_chat_solitaires(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[Solitaire]:
    """
    获取群组的接龙列表

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        active_only: 是否只返回进行中的接龙

    Returns:
        接龙列表
    """
    # 使用基础查询获取列表
    solitaires = await ServiceBase._get_list(
        session,
        Solitaire,
        filters={"chat_id": chat_id},
        order_by="created_at",
        descending=True,
    )

    # 根据 active_only 过滤
    if active_only:
        solitaires = [s for s in solitaires if s.status == SolitaireStatus.active.value]

    # 为每个接龙加载参与记录
    result = []
    for solitaire in solitaires:
        stmt = select(Solitaire).options(
            selectinload(Solitaire.entries_rel)
        ).where(Solitaire.id == solitaire.id)
        solitaire_result = await session.execute(stmt)
        loaded_solitaire = solitaire_result.scalar_one_or_none()
        if loaded_solitaire:
            result.append(loaded_solitaire)

    return result


async def get_solitaire(
    session: AsyncSession,
    solitaire_id: int,
) -> Solitaire | None:
    """
    获取接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID

    Returns:
        Solitaire: 接龙对象，如果不存在则返回 None
    """
    stmt = select(Solitaire).options(
        selectinload(Solitaire.entries_rel)
    ).where(Solitaire.id == solitaire_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_solitaire_in_chat(
    session: AsyncSession,
    chat_id: int,
    solitaire_id: int,
) -> Solitaire | None:
    """按群组作用域获取接龙，避免跨群访问。"""
    stmt = select(Solitaire).options(
        selectinload(Solitaire.entries_rel)
    ).where(
        Solitaire.id == solitaire_id,
        Solitaire.chat_id == chat_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_solitaire_stats(
    session: AsyncSession,
    chat_id: int,
) -> dict[str, int]:
    """
    获取接龙统计

    Args:
        session: 数据库会话
        chat_id: 群组 ID

    Returns:
        统计数据字典，包含 total, active, closed, total_entries
    """
    solitaires = await get_chat_solitaires(session, chat_id)
    total_entries = 0
    for s in solitaires:
        # 使用 entries_rel 关系获取参与记录数量
        total_entries += len(s.entries_rel)
    return {
        "total": len(solitaires),
        "active": sum(1 for s in solitaires if s.status == SolitaireStatus.active.value),
        "closed": sum(1 for s in solitaires if s.status == SolitaireStatus.closed.value),
        "total_entries": total_entries,
    }
