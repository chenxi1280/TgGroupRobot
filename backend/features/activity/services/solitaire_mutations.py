from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.solitaire_queries import get_solitaire, get_solitaire_in_chat
from backend.platform.db.schema.models.core import PointsAccount, Solitaire, SolitaireEntry
from backend.platform.db.schema.models.enums import SolitaireStatus
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CloseResult, CreateResult, JoinResult

SolitaireLookup = Callable[[AsyncSession, int], Awaitable[Solitaire | None]]
ScopedSolitaireLookup = Callable[[AsyncSession, int, int], Awaitable[Solitaire | None]]

log = structlog.get_logger(__name__)


async def create_solitaire(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    *, title: str,
    description: str | None = None,
    max_participants: int | None = None,
    points_required: int | None = None,
    deadline: dt.datetime | None = None,
) -> CreateResult:
    """创建接龙并重新加载关系数据。"""
    try:
        solitaire = Solitaire(
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            title=title,
            description=description,
            status=SolitaireStatus.active.value,
            max_participants=max_participants,
            points_required=points_required,
            deadline=deadline,
        )
        session.add(solitaire)
        await session.flush()

        # 重新查询以正确加载关系
        solitaire = await get_solitaire(session, solitaire.id)
        if solitaire is None:
            return CreateResult(success=False, reason="error", error="接龙创建后查询失败")

        return CreateResult(
            success=True,
            reason="ok",
            entity=solitaire,
            entity_id=solitaire.id,
            message_id=None,
        )
    except Exception as exc:
        log.exception(
            "create_solitaire_failed",
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            error=str(exc),
        )
        return CreateResult(success=False, reason="error", error="接龙创建失败，请稍后重试")


async def _has_solitaire_points(session, solitaire, user_id: int) -> bool:
    required = int(solitaire.points_required or 0)
    if required <= 0:
        return True
    account = await ServiceBase._get_by_filters(
        session,
        PointsAccount,
        {"chat_id": solitaire.chat_id, "user_id": user_id},
    )
    return int(account.balance if account else 0) >= required


async def _solitaire_join_rejection(session, solitaire, *, solitaire_id: int, user_id: int) -> JoinResult | None:
    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", entity=solitaire)
    if solitaire.deadline and dt.datetime.now(dt.UTC) > solitaire.deadline:
        return JoinResult(success=False, reason="expired", entity=solitaire)
    existing = await ServiceBase._get_by_filters(
        session,
        SolitaireEntry,
        {"solitaire_id": solitaire_id, "user_id": user_id},
    )
    if existing:
        return JoinResult(success=False, reason="already_joined", entity=solitaire)
    if solitaire.max_participants and len(solitaire.entries_rel) >= solitaire.max_participants:
        return JoinResult(success=False, reason="full", entity=solitaire)
    if not await _has_solitaire_points(session, solitaire, user_id):
        return JoinResult(success=False, reason="insufficient_points", entity=solitaire)
    return None


async def join_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
    *, username: str | None,
    content: str,
) -> JoinResult:
    """校验资格并参与接龙。"""
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")
    rejection = await _solitaire_join_rejection(
        session, solitaire, solitaire_id=solitaire_id, user_id=user_id
    )
    if rejection is not None:
        return rejection
    entry = SolitaireEntry(
        solitaire_id=solitaire_id,
        user_id=user_id,
        username=username,
        content=content,
        joined_at=dt.datetime.now(dt.UTC),
    )
    session.add(entry)
    return JoinResult(success=True, reason="ok", entity=solitaire)


async def update_entry(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
    *, content: str,
) -> JoinResult:
    """
    更新参与内容

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID
        user_id: 用户 ID
        content: 新的参与内容

    Returns:
        JoinResult: 更新结果
    """
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", entity=solitaire)

    # 查找并更新
    entry = await ServiceBase._get_by_filters(
        session,
        SolitaireEntry,
        {"solitaire_id": solitaire_id, "user_id": user_id},
    )

    if entry:
        await ServiceBase._update_entity(
            session,
            entry,
            {
                "content": content,
                "updated_at": dt.datetime.now(dt.UTC),
            },
        )
        return JoinResult(success=True, reason="ok", entity=solitaire)

    return JoinResult(success=False, reason="not_found", entity=solitaire)


async def leave_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
) -> JoinResult:
    """
    退出接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID
        user_id: 用户 ID

    Returns:
        JoinResult: 退出结果
    """
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", entity=solitaire)

    # 查找并删除
    entry = await ServiceBase._get_by_filters(
        session,
        SolitaireEntry,
        {"solitaire_id": solitaire_id, "user_id": user_id},
    )

    if entry:
        await ServiceBase._delete_entity(session, entry)
        return JoinResult(success=True, reason="ok", entity=solitaire)

    return JoinResult(success=False, reason="not_found", entity=solitaire)


async def close_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    *,
    chat_id: int | None = None,
    lookup: SolitaireLookup = get_solitaire,
    scoped_lookup: ScopedSolitaireLookup = get_solitaire_in_chat,
) -> CloseResult:
    """
    结束接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID

    Returns:
        CloseResult: 结束结果
    """
    solitaire = await (
        scoped_lookup(session, chat_id, solitaire_id)
        if chat_id is not None
        else lookup(session, solitaire_id)
    )
    if not solitaire:
        return CloseResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return CloseResult(success=False, reason="already_closed", entity=solitaire)

    await ServiceBase._update_entity(
        session,
        solitaire,
        {"status": SolitaireStatus.closed.value},
    )
    return CloseResult(success=True, reason="ok", entity=solitaire)


async def delete_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    *,
    chat_id: int | None = None,
    lookup: SolitaireLookup = get_solitaire,
    scoped_lookup: ScopedSolitaireLookup = get_solitaire_in_chat,
) -> bool:
    """
    删除接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID

    Returns:
        是否删除成功
    """
    solitaire = await (
        scoped_lookup(session, chat_id, solitaire_id)
        if chat_id is not None
        else lookup(session, solitaire_id)
    )
    if not solitaire:
        return False
    await ServiceBase._delete_entity(session, solitaire)
    return True
