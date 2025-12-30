from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import Solitaire
from bot.models.enums import SolitaireStatus


@dataclass
class CreateResult:
    """创建接龙结果"""
    success: bool
    reason: Literal["ok", "error"]
    solitaire: Solitaire | None = None


@dataclass
class JoinResult:
    """参与接龙结果"""
    success: bool
    reason: Literal["ok", "not_found", "already_closed", "already_joined", "full", "error"]
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
            entries=[],
        )
        session.add(solitaire)
        await session.flush()
        return CreateResult(success=True, reason="ok", solitaire=solitaire)
    except Exception:
        return CreateResult(success=False, reason="error")


async def get_chat_solitaires(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[Solitaire]:
    """获取群组的接龙列表"""
    stmt = select(Solitaire).where(Solitaire.chat_id == chat_id)
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
    stmt = select(Solitaire).where(Solitaire.id == solitaire_id)
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

    # 检查是否已参与
    for entry in solitaire.entries:
        if entry.get("user_id") == user_id:
            return JoinResult(success=False, reason="already_joined", solitaire=solitaire)

    # 检查人数限制
    if solitaire.max_participants and len(solitaire.entries) >= solitaire.max_participants:
        return JoinResult(success=False, reason="full", solitaire=solitaire)

    # 添加参与记录
    entry = {
        "user_id": user_id,
        "username": username,
        "content": content,
        "joined_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    solitaire.entries.append(entry)
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
    for entry in solitaire.entries:
        if entry.get("user_id") == user_id:
            entry["content"] = content
            entry["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
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
    for i, entry in enumerate(solitaire.entries):
        if entry.get("user_id") == user_id:
            solitaire.entries.pop(i)
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
    return {
        "total": len(solitaires),
        "active": sum(1 for s in solitaires if s.status == SolitaireStatus.active.value),
        "closed": sum(1 for s in solitaires if s.status == SolitaireStatus.closed.value),
        "total_entries": sum(len(s.entries) for s in solitaires),
    }


def format_solitaire_message(solitaire: Solitaire, show_closed: bool = True) -> str:
    """格式化接龙消息"""
    status_emoji = "🟢" if solitaire.status == SolitaireStatus.active.value else "🔴"
    status_text = "进行中" if solitaire.status == SolitaireStatus.active.value else "已结束"

    text = f"{status_emoji} {solitaire.title}\n"
    text += f"状态: {status_text}"
    if solitaire.max_participants:
        text += f" ({len(solitaire.entries)}/{solitaire.max_participants}人)"
    else:
        text += f" ({len(solitaire.entries)}人)"
    text += "\n"

    if solitaire.description:
        text += f"\n{solitaire.description}\n"

    if solitaire.entries:
        text += "\n参与列表:\n"
        for i, entry in enumerate(solitaire.entries, 1):
            username = entry.get("username") or f"用户{entry.get('user_id')}"
            content = entry.get("content", "")
            text += f"{i}. {username}: {content}\n"
    else:
        text += "\n暂无人参与，快来接龙吧！\n"

    if solitaire.status == SolitaireStatus.active.value and show_closed:
        text += "\n💡 回复接龙消息即可参与"

    return text
