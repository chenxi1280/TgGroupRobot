"""续费卡密的 API 序列化与关联信息装载。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import (
    ChatMember,
    RenewalCardKey,
    RenewalCardKeyBatch,
    TgChat,
    TgUser,
)


def _format_user(
    user_id: int | None,
    username: str | None,
    first_name: str | None,
    *,
    last_name: str | None,
) -> str:
    if user_id is None:
        return ""
    name = " ".join(part for part in [first_name, last_name] if part).strip()
    if username:
        return f"{name or username} (@{username})"
    return name or str(user_id)


def is_card_voided(card: RenewalCardKey) -> bool:
    return str(getattr(card, "copy_status", "") or "") == "voided"


def serialize_batch(
    batch: RenewalCardKeyBatch,
    *,
    used_count: int = 0,
    voided_count: int = 0,
) -> dict[str, Any]:
    quantity = int(batch.quantity or 0)
    used = int(used_count or 0)
    voided = int(voided_count or 0)
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "spec_days": batch.spec_days,
        "quantity": batch.quantity,
        "used_count": used,
        "voided_count": voided,
        "available_count": max(quantity - used - voided, 0),
        "copy_count": batch.copy_count,
        "export_count": batch.export_count,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
    }


def serialize_card(card: RenewalCardKey) -> dict[str, Any]:
    voided = is_card_voided(card)
    return {
        "id": card.id,
        "batch_id": card.batch_id,
        "card_code": card.card_code_plain,
        "has_plaintext": bool(card.card_code_plain),
        "spec_days": card.spec_days,
        "duration_seconds": card.duration_seconds,
        "used": bool(card.used),
        "voided": voided,
        "status": "voided" if voided else ("used" if card.used else "available"),
        "used_by_chat_id": card.used_by_chat_id,
        "used_by_user_id": card.used_by_user_id,
        "used_at": card.used_at.isoformat() if card.used_at else None,
        "copy_status": card.copy_status,
        "export_status": card.export_status,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }


async def _load_chat_map(session: AsyncSession, chat_ids: set[int]) -> dict[int, str]:
    if not chat_ids:
        return {}
    chats = (
        await session.execute(select(TgChat).where(TgChat.id.in_(chat_ids)))
    ).scalars().all()
    return {chat.id: chat.title or f"群组{chat.id}" for chat in chats}


async def _load_user_map(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    users = (
        await session.execute(select(TgUser).where(TgUser.id.in_(user_ids)))
    ).scalars().all()
    return {
        user.id: _format_user(
            user.id,
            user.username,
            user.first_name,
            last_name=user.last_name,
        )
        for user in users
    }


async def _load_owner_map(session: AsyncSession, chat_ids: set[int]) -> dict[int, str]:
    if not chat_ids:
        return {}
    rows = (
        await session.execute(
            select(ChatMember.chat_id, TgUser.id, TgUser.username, TgUser.first_name, TgUser.last_name)
            .join(TgUser, TgUser.id == ChatMember.user_id)
            .where(ChatMember.chat_id.in_(chat_ids))
            .where(ChatMember.role == "owner")
        )
    ).all()
    owners: dict[int, str] = {}
    for chat_id, user_id, username, first_name, last_name in rows:
        owners.setdefault(
            int(chat_id),
            _format_user(user_id, username, first_name, last_name=last_name),
        )
    return owners


def _serialize_with_context(
    card: RenewalCardKey,
    *,
    chat_map: dict[int, str],
    user_map: dict[int, str],
    owner_map: dict[int, str],
) -> dict[str, Any]:
    item = serialize_card(card)
    chat_id = card.used_by_chat_id
    item["used_by_chat_title"] = chat_map.get(chat_id, f"群组{chat_id}") if chat_id else ""
    item["owner_text"] = owner_map.get(chat_id, "") if chat_id else ""
    item["used_by_user_text"] = user_map.get(card.used_by_user_id or 0, "")
    return item


async def serialize_cards(
    session: AsyncSession,
    cards: list[RenewalCardKey],
) -> list[dict[str, Any]]:
    if not cards:
        return []
    chat_ids = {card.used_by_chat_id for card in cards if card.used_by_chat_id is not None}
    user_ids = {card.used_by_user_id for card in cards if card.used_by_user_id is not None}
    chat_map = await _load_chat_map(session, chat_ids)
    user_map = await _load_user_map(session, user_ids)
    owner_map = await _load_owner_map(session, chat_ids)
    return [
        _serialize_with_context(
            card,
            chat_map=chat_map,
            user_map=user_map,
            owner_map=owner_map,
        )
        for card in cards
    ]
