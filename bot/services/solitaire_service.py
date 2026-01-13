from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.core import Solitaire, SolitaireEntry
from bot.models.enums import SolitaireStatus


@dataclass
class CreateResult:
    """创建接龙结果"""
    success: bool
    reason: Literal["ok", "error"]
    solitaire: Solitaire | None = None
    message_id: int | None = None
    error: str | None = None


@dataclass
class JoinResult:
    """参与接龙结果"""
    success: bool
    reason: Literal["ok", "not_found", "already_closed", "already_joined", "full", "expired", "insufficient_points", "error"]
    solitaire: Solitaire | None = None


@dataclass
class CloseResult:
    """结束接龙结果"""
    success: bool
    reason: Literal["ok", "not_found", "already_closed", "error"]
    solitaire: Solitaire | None = None


async def create_solitaire(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    title: str,
    description: str | None = None,
    max_participants: int | None = None,
    points_required: int | None = None,
    deadline: dt.datetime | None = None,
) -> CreateResult:
    """创建接龙"""
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
        stmt = select(Solitaire).options(
            selectinload(Solitaire.entries_rel)
        ).where(Solitaire.id == solitaire.id)
        result = await session.execute(stmt)
        solitaire = result.scalar_one_or_none()
        if solitaire is None:
            return CreateResult(success=False, reason="error", error="接龙创建后查询失败")

        return CreateResult(success=True, reason="ok", solitaire=solitaire)
    except Exception:
        return CreateResult(success=False, reason="error")


async def get_chat_solitaires(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[Solitaire]:
    """获取群组的接龙列表"""
    stmt = select(Solitaire).options(
        selectinload(Solitaire.entries_rel)
    ).where(Solitaire.chat_id == chat_id)
    if active_only:
        stmt = stmt.where(Solitaire.status == SolitaireStatus.active.value)
    stmt = stmt.order_by(Solitaire.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_solitaire(
    session: AsyncSession,
    solitaire_id: int,
) -> Solitaire | None:
    """获取接龙"""
    stmt = select(Solitaire).options(
        selectinload(Solitaire.entries_rel)
    ).where(Solitaire.id == solitaire_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def join_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
    username: str | None,
    content: str,
) -> JoinResult:
    """参与接龙"""
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", solitaire=solitaire)

    # 检查截止时间
    if solitaire.deadline:
        now = dt.datetime.now(dt.timezone.utc)
        if now > solitaire.deadline:
            return JoinResult(success=False, reason="expired", solitaire=solitaire)

    # 检查是否已参与（查询数据库）
    existing_stmt = select(SolitaireEntry).where(
        SolitaireEntry.solitaire_id == solitaire_id,
        SolitaireEntry.user_id == user_id
    )
    existing_result = await session.execute(existing_stmt)
    if existing_result.scalar_one_or_none():
        return JoinResult(success=False, reason="already_joined", solitaire=solitaire)

    # 检查人数限制
    current_count = len(solitaire.entries_rel)
    if solitaire.max_participants and current_count >= solitaire.max_participants:
        return JoinResult(success=False, reason="full", solitaire=solitaire)

    # 检查积分限制
    if solitaire.points_required and solitaire.points_required > 0:
        from bot.models.core import PointsAccount
        # 如果用户没有积分账户，user_points 默认为 0
        user_points = 0
        points_stmt = select(PointsAccount).where(
            PointsAccount.chat_id == solitaire.chat_id,
            PointsAccount.user_id == user_id
        )
        points_result = await session.execute(points_stmt)
        points_account = points_result.scalar_one_or_none()
        if points_account:
            user_points = points_account.balance

        if user_points < solitaire.points_required:
            return JoinResult(success=False, reason="insufficient_points", solitaire=solitaire)

    # 创建参与记录
    entry = SolitaireEntry(
        solitaire_id=solitaire_id,
        user_id=user_id,
        username=username,
        content=content,
        joined_at=dt.datetime.now(dt.UTC),
    )
    session.add(entry)
    return JoinResult(success=True, reason="ok", solitaire=solitaire)


async def update_entry(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
    content: str,
) -> JoinResult:
    """更新参与内容"""
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", solitaire=solitaire)

    # 查找并更新
    stmt = select(SolitaireEntry).where(
        SolitaireEntry.solitaire_id == solitaire_id,
        SolitaireEntry.user_id == user_id
    )
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()

    if entry:
        entry.content = content
        entry.updated_at = dt.datetime.now(dt.UTC)
        return JoinResult(success=True, reason="ok", solitaire=solitaire)

    return JoinResult(success=False, reason="not_found", solitaire=solitaire)


async def leave_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
) -> JoinResult:
    """退出接龙"""
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", solitaire=solitaire)

    # 查找并删除
    stmt = select(SolitaireEntry).where(
        SolitaireEntry.solitaire_id == solitaire_id,
        SolitaireEntry.user_id == user_id
    )
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()

    if entry:
        await session.delete(entry)
        return JoinResult(success=True, reason="ok", solitaire=solitaire)

    return JoinResult(success=False, reason="not_found", solitaire=solitaire)


async def close_solitaire(
    session: AsyncSession,
    solitaire_id: int,
) -> CloseResult:
    """结束接龙"""
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return CloseResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return CloseResult(success=False, reason="already_closed", solitaire=solitaire)

    solitaire.status = SolitaireStatus.closed.value
    return CloseResult(success=True, reason="ok", solitaire=solitaire)


async def delete_solitaire(
    session: AsyncSession,
    solitaire_id: int,
) -> bool:
    """删除接龙"""
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return False
    await session.delete(solitaire)
    return True


async def get_solitaire_stats(
    session: AsyncSession,
    chat_id: int,
) -> dict[str, int]:
    """获取接龙统计"""
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


def format_solitaire_message(solitaire: Solitaire, show_closed: bool = True) -> str:
    """格式化接龙消息"""
    status_emoji = "🟢" if solitaire.status == SolitaireStatus.active.value else "🔴"
    status_text = "进行中" if solitaire.status == SolitaireStatus.active.value else "已结束"

    text = f"{status_emoji} {solitaire.title}\n"
    text += f"状态: {status_text}"

    # 使用 entries_rel 获取参与记录
    entries_count = len(solitaire.entries_rel)
    if solitaire.max_participants:
        text += f" ({entries_count}/{solitaire.max_participants}人)"
    else:
        text += f" ({entries_count}人)"
    text += "\n"

    # 积分限制
    if solitaire.points_required:
        text += f"💎 需积分: {solitaire.points_required}\n"

    # 截止时间
    if solitaire.deadline:
        deadline_str = solitaire.deadline.strftime("%Y-%m-%d %H:%M")
        text += f"⏰ 截止: {deadline_str}\n"

    if solitaire.description:
        text += f"\n{solitaire.description}\n"

    # 使用 entries_rel 关系显示参与列表
    if solitaire.entries_rel:
        text += "\n参与列表:\n"
        for i, entry in enumerate(solitaire.entries_rel, 1):
            username = entry.username or f"用户{entry.user_id}"
            text += f"{i}. {username}: {entry.content}\n"
    else:
        text += "\n暂无人参与，快来接龙吧！\n"

    if solitaire.status == SolitaireStatus.active.value and show_closed:
        text += "\n💡 回复接龙消息即可参与"

    return text
