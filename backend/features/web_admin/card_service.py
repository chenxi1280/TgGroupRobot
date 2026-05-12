from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.subscription.services.renewal_service import hash_card_code, normalize_card_code
from backend.features.web_admin.auth_service import append_audit
from backend.platform.db.schema.models.core import (
    AdminAccount,
    ChatMember,
    RenewalCardKey,
    RenewalCardKeyBatch,
    TgChat,
    TgUser,
)


COPY_CARD_LIMIT = 40
KEY_SPECS = [
    {"days": 30, "label": "30天"},
    {"days": 60, "label": "60天"},
    {"days": 90, "label": "90天"},
    {"days": 365, "label": "一年"},
]

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


@dataclass(slots=True)
class CopyResult:
    count: int
    total: int
    copied_text: str
    truncated: bool = False


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _spec_days(value: int) -> int:
    days = int(value)
    allowed = {item["days"] for item in KEY_SPECS}
    if days not in allowed:
        raise ValueError("不支持的卡密规格")
    return days


def _format_user(user_id: int | None, username: str | None, first_name: str | None, last_name: str | None) -> str:
    if user_id is None:
        return ""
    name = " ".join(part for part in [first_name, last_name] if part).strip()
    if username:
        return f"{name or username} (@{username})"
    return name or str(user_id)


def _generate_card_code() -> str:
    chunks = [
        "".join(secrets.choice(_ALPHABET) for _ in range(4))
        for _ in range(4)
    ]
    return "TGR-" + "-".join(chunks)


def _batch_no() -> str:
    timestamp = _utcnow().strftime("%Y%m%d%H%M%S")
    return f"RK{timestamp}{secrets.token_hex(3).upper()}"


def is_card_voided(card: RenewalCardKey) -> bool:
    return str(getattr(card, "copy_status", "") or "") == "voided"


async def _ensure_unique_card_code(session: AsyncSession) -> str:
    for _ in range(20):
        code = _generate_card_code()
        result = await session.execute(
            select(RenewalCardKey.id).where(RenewalCardKey.card_key_hash == hash_card_code(code)).limit(1)
        )
        if result.scalar_one_or_none() is None:
            return code
    raise RuntimeError("生成唯一卡密失败，请重试")


async def generate_card_batch(
    session: AsyncSession,
    *,
    admin: AdminAccount,
    spec_days: int,
    quantity: int,
) -> dict[str, Any]:
    days = _spec_days(spec_days)
    count = int(quantity)
    if count <= 0:
        raise ValueError("生成数量必须大于 0")
    if count > 500:
        raise ValueError("单批最多生成 500 个卡密")

    batch = RenewalCardKeyBatch(
        batch_no=_batch_no(),
        spec_days=days,
        quantity=count,
        created_by_admin_id=admin.id,
    )
    session.add(batch)
    await session.flush()

    cards: list[RenewalCardKey] = []
    for _ in range(count):
        code = await _ensure_unique_card_code(session)
        card = RenewalCardKey(
            batch_id=batch.id,
            card_code_plain=normalize_card_code(code),
            card_key_hash=hash_card_code(code),
            spec_days=days,
            created_by_admin_id=admin.id,
            duration_seconds=days * 86400,
            expires_at=None,
        )
        session.add(card)
        cards.append(card)
    await session.flush()

    await append_audit(
        session,
        admin_account_id=admin.id,
        action="renewal.batch.generate",
        target_type="renewal_card_key_batch",
        target_id=str(batch.id),
        detail={"batch_no": batch.batch_no, "spec_days": days, "quantity": count},
    )

    copy_cards = cards[-COPY_CARD_LIMIT:]
    copied_text = "\n".join(card.card_code_plain or "" for card in copy_cards if card.card_code_plain)
    return {
        "batch": serialize_batch(batch, used_count=0),
        "cards": [serialize_card(card) for card in cards],
        "copied_text": copied_text,
        "copied_count": len(copy_cards),
        "copy_limit": COPY_CARD_LIMIT,
        "truncated": count > len(copy_cards),
    }


async def list_batches(
    session: AsyncSession,
    *,
    spec_days: int | None = None,
    keyword: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    conditions = []
    if spec_days:
        conditions.append(RenewalCardKeyBatch.spec_days == _spec_days(spec_days))
    keyword_value = (keyword or "").strip()
    if keyword_value:
        conditions.append(RenewalCardKeyBatch.batch_no.ilike(f"%{keyword_value}%"))

    total = int(
        (
            await session.execute(
                select(func.count(RenewalCardKeyBatch.id)).where(*conditions)
            )
        ).scalar()
        or 0
    )
    batches = (
        await session.execute(
            select(RenewalCardKeyBatch)
            .where(*conditions)
            .order_by(RenewalCardKeyBatch.created_at.desc(), RenewalCardKeyBatch.id.desc())
            .limit(max(1, min(int(limit), 500)))
            .offset(max(0, int(offset)))
        )
    ).scalars().all()
    if not batches:
        return {"items": [], "total": total}

    batch_ids = [batch.id for batch in batches]
    stats_rows = (
        await session.execute(
            select(
                RenewalCardKey.batch_id,
                func.count(RenewalCardKey.id),
                func.sum(case((RenewalCardKey.used.is_(True), 1), else_=0)),
                func.sum(case((RenewalCardKey.copy_status == "voided", 1), else_=0)),
            )
            .where(RenewalCardKey.batch_id.in_(batch_ids))
            .group_by(RenewalCardKey.batch_id)
        )
    ).all()
    stats = {
        int(batch_id): {
            "total": int(total_count or 0),
            "used": int(used_count or 0),
            "voided": int(voided_count or 0),
        }
        for batch_id, total_count, used_count, voided_count in stats_rows
        if batch_id is not None
    }
    return {
        "items": [
            serialize_batch(
                batch,
                used_count=stats.get(batch.id, {}).get("used", 0),
                voided_count=stats.get(batch.id, {}).get("voided", 0),
            )
            for batch in batches
        ],
        "total": total,
    }


def _card_filters(
    *,
    spec_days: int | None,
    batch_id: int | None,
    status: str | None,
    keyword: str | None,
) -> list[Any]:
    conditions: list[Any] = []
    if spec_days:
        conditions.append(RenewalCardKey.spec_days == _spec_days(spec_days))
    if batch_id:
        conditions.append(RenewalCardKey.batch_id == int(batch_id))
    if status == "used":
        conditions.append(RenewalCardKey.used.is_(True))
    elif status == "available":
        conditions.append(RenewalCardKey.used.is_(False))
        conditions.append(or_(RenewalCardKey.copy_status.is_(None), RenewalCardKey.copy_status != "voided"))
    elif status in {"voided", "invalid"}:
        conditions.append(RenewalCardKey.copy_status == "voided")
    keyword_value = (keyword or "").strip()
    if keyword_value:
        conditions.append(
            or_(
                RenewalCardKey.card_code_plain.ilike(f"%{keyword_value}%"),
                RenewalCardKeyBatch.batch_no.ilike(f"%{keyword_value}%"),
            )
        )
    return conditions


async def list_cards(
    session: AsyncSession,
    *,
    spec_days: int | None = None,
    batch_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    conditions = _card_filters(spec_days=spec_days, batch_id=batch_id, status=status, keyword=keyword)
    total = int(
        (
            await session.execute(
                select(func.count(RenewalCardKey.id))
                .outerjoin(RenewalCardKeyBatch, RenewalCardKeyBatch.id == RenewalCardKey.batch_id)
                .where(*conditions)
            )
        ).scalar()
        or 0
    )
    cards = (
        await session.execute(
            select(RenewalCardKey)
            .outerjoin(RenewalCardKeyBatch, RenewalCardKeyBatch.id == RenewalCardKey.batch_id)
            .where(*conditions)
            .order_by(RenewalCardKey.created_at.desc(), RenewalCardKey.id.desc())
            .limit(max(1, min(int(limit), 500)))
            .offset(max(0, int(offset)))
        )
    ).scalars().all()
    return {
        "items": await serialize_cards(session, cards),
        "total": total,
    }


async def copy_cards(
    session: AsyncSession,
    *,
    admin: AdminAccount,
    card_ids: list[int],
    with_meta: bool = False,
) -> CopyResult:
    ids = [int(item) for item in card_ids if int(item) > 0]
    if not ids:
        raise ValueError("请选择要复制的卡密")
    if len(ids) > COPY_CARD_LIMIT:
        raise ValueError(f"单次最多复制 {COPY_CARD_LIMIT} 个卡密，请改用导出")

    cards = (
        await session.execute(
            select(RenewalCardKey)
            .where(RenewalCardKey.id.in_(ids))
            .order_by(RenewalCardKey.created_at.asc(), RenewalCardKey.id.asc())
        )
    ).scalars().all()
    if len(cards) != len(set(ids)):
        raise ValueError("部分卡密不存在")
    if any(is_card_voided(card) for card in cards):
        raise ValueError("包含已作废卡密，无法复制")
    if any(card.used for card in cards):
        raise ValueError("包含已激活卡密，无法复制")
    if any(not card.card_code_plain for card in cards):
        raise ValueError("包含历史卡密，无法复制明文")

    now = _utcnow()
    lines = []
    for card in cards:
        card.copy_status = "copied"
        card.copied_at = now
        if with_meta:
            lines.append(f"{card.card_code_plain} | {card.spec_days or '-'}天 | 批次{card.batch_id or '-'}")
        else:
            lines.append(card.card_code_plain or "")

    batch_ids = {card.batch_id for card in cards if card.batch_id}
    if batch_ids:
        batches = (
            await session.execute(select(RenewalCardKeyBatch).where(RenewalCardKeyBatch.id.in_(batch_ids)))
        ).scalars().all()
        for batch in batches:
            batch.copy_count += 1

    await append_audit(
        session,
        admin_account_id=admin.id,
        action="renewal.cards.copy",
        target_type="renewal_card_key",
        target_id=",".join(str(item) for item in ids),
        detail={"count": len(cards), "with_meta": with_meta},
    )
    return CopyResult(count=len(cards), total=len(cards), copied_text="\n".join(lines))


async def void_cards(
    session: AsyncSession,
    *,
    admin: AdminAccount,
    card_ids: list[int],
) -> dict[str, Any]:
    ids = [int(item) for item in card_ids if int(item) > 0]
    if not ids:
        raise ValueError("请选择要作废的卡密")

    cards = (
        await session.execute(
            select(RenewalCardKey)
            .where(RenewalCardKey.id.in_(ids))
            .with_for_update()
        )
    ).scalars().all()
    if len(cards) != len(set(ids)):
        raise ValueError("部分卡密不存在")

    used = [card.id for card in cards if card.used]
    if used:
        raise ValueError("已激活卡密不能作废")

    changed = 0
    now = _utcnow()
    for card in cards:
        if is_card_voided(card):
            continue
        card.copy_status = "voided"
        card.export_status = "voided"
        card.copied_at = now
        changed += 1

    await append_audit(
        session,
        admin_account_id=admin.id,
        action="renewal.cards.void",
        target_type="renewal_card_key",
        target_id=",".join(str(item) for item in ids),
        detail={"count": len(cards), "changed": changed},
    )
    return {"count": len(cards), "changed": changed}


async def rows_for_export(
    session: AsyncSession,
    *,
    admin: AdminAccount,
    spec_days: int | None = None,
    batch_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    conditions = _card_filters(spec_days=spec_days, batch_id=batch_id, status=status, keyword=keyword)
    cards = (
        await session.execute(
            select(RenewalCardKey)
            .outerjoin(RenewalCardKeyBatch, RenewalCardKeyBatch.id == RenewalCardKey.batch_id)
            .where(*conditions)
            .order_by(RenewalCardKey.created_at.asc(), RenewalCardKey.id.asc())
            .limit(5000)
        )
    ).scalars().all()
    now = _utcnow()
    for card in cards:
        card.export_status = "exported"
        card.exported_at = now

    batch_ids = {card.batch_id for card in cards if card.batch_id}
    if batch_ids:
        batches = (
            await session.execute(select(RenewalCardKeyBatch).where(RenewalCardKeyBatch.id.in_(batch_ids)))
        ).scalars().all()
        for batch in batches:
            batch.export_count += 1

    await append_audit(
        session,
        admin_account_id=admin.id,
        action="renewal.cards.export",
        target_type="renewal_card_key",
        target_id=str(batch_id or "filtered"),
        detail={"count": len(cards), "spec_days": spec_days, "status": status, "keyword": keyword},
    )
    return await serialize_cards(session, cards)


def serialize_batch(batch: RenewalCardKeyBatch, *, used_count: int = 0, voided_count: int = 0) -> dict[str, Any]:
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


async def serialize_cards(session: AsyncSession, cards: list[RenewalCardKey]) -> list[dict[str, Any]]:
    if not cards:
        return []
    chat_ids = {card.used_by_chat_id for card in cards if card.used_by_chat_id is not None}
    user_ids = {card.used_by_user_id for card in cards if card.used_by_user_id is not None}

    chat_map: dict[int, str] = {}
    if chat_ids:
        chats = (await session.execute(select(TgChat).where(TgChat.id.in_(chat_ids)))).scalars().all()
        chat_map = {chat.id: chat.title or f"群组{chat.id}" for chat in chats}

    user_map: dict[int, str] = {}
    if user_ids:
        users = (await session.execute(select(TgUser).where(TgUser.id.in_(user_ids)))).scalars().all()
        user_map = {
            user.id: _format_user(user.id, user.username, user.first_name, user.last_name)
            for user in users
        }

    owner_map: dict[int, str] = {}
    if chat_ids:
        owner_rows = (
            await session.execute(
                select(ChatMember.chat_id, TgUser.id, TgUser.username, TgUser.first_name, TgUser.last_name)
                .join(TgUser, TgUser.id == ChatMember.user_id)
                .where(ChatMember.chat_id.in_(chat_ids))
                .where(ChatMember.role == "owner")
            )
        ).all()
        for chat_id, user_id, username, first_name, last_name in owner_rows:
            owner_map.setdefault(int(chat_id), _format_user(user_id, username, first_name, last_name))

    items = []
    for card in cards:
        item = serialize_card(card)
        if card.used_by_chat_id is not None:
            item["used_by_chat_title"] = chat_map.get(card.used_by_chat_id, f"群组{card.used_by_chat_id}")
            item["owner_text"] = owner_map.get(card.used_by_chat_id, "")
        else:
            item["used_by_chat_title"] = ""
            item["owner_text"] = ""
        item["used_by_user_text"] = user_map.get(card.used_by_user_id or 0, "")
        items.append(item)
    return items
