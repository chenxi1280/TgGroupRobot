from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.subscription.services.renewal_service import hash_card_code, normalize_card_code
from backend.features.web_admin.auth_service import append_audit
from backend.features.web_admin.card_serialization import (
    is_card_voided,
    serialize_batch,
    serialize_card,
    serialize_cards,
)
from backend.platform.db.schema.models.core import (
    AdminAccount,
    RenewalCardKey,
    RenewalCardKeyBatch,
)


COPY_CARD_LIMIT = 40
MAX_BATCH_QUANTITY = 500
SECONDS_PER_DAY = 86_400
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


def _generate_card_code() -> str:
    chunks = [
        "".join(secrets.choice(_ALPHABET) for _ in range(4))
        for _ in range(4)
    ]
    return "TGR-" + "-".join(chunks)


def _batch_no() -> str:
    timestamp = _utcnow().strftime("%Y%m%d%H%M%S")
    return f"RK{timestamp}{secrets.token_hex(3).upper()}"


async def _ensure_unique_card_code(session: AsyncSession) -> str:
    for _ in range(20):
        code = _generate_card_code()
        result = await session.execute(
            select(RenewalCardKey.id).where(RenewalCardKey.card_key_hash == hash_card_code(code)).limit(1)
        )
        if result.scalar_one_or_none() is None:
            return code
    raise RuntimeError("生成唯一卡密失败，请重试")


async def _generate_cards(
    session: AsyncSession,
    batch: RenewalCardKeyBatch,
    *,
    admin_id: int,
    days: int,
    count: int,
) -> list[RenewalCardKey]:
    cards = []
    for _ in range(count):
        code = await _ensure_unique_card_code(session)
        card = RenewalCardKey(
            batch_id=batch.id,
            card_code_plain=normalize_card_code(code),
            card_key_hash=hash_card_code(code),
            spec_days=days,
            created_by_admin_id=admin_id,
            duration_seconds=days * SECONDS_PER_DAY,
            expires_at=None,
        )
        session.add(card)
        cards.append(card)
    await session.flush()
    return cards


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
    if count > MAX_BATCH_QUANTITY:
        raise ValueError("单批最多生成 500 个卡密")

    batch = RenewalCardKeyBatch(
        batch_no=_batch_no(),
        spec_days=days,
        quantity=count,
        created_by_admin_id=admin.id,
    )
    session.add(batch)
    await session.flush()

    cards = await _generate_cards(
        session,
        batch,
        admin_id=admin.id,
        days=days,
        count=count,
    )

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
    conditions = _batch_filters(spec_days=spec_days, keyword=keyword)

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
    stats = await _load_batch_stats(session, batch_ids)
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


def _batch_filters(*, spec_days: int | None, keyword: str | None) -> list[Any]:
    conditions = []
    if spec_days:
        conditions.append(RenewalCardKeyBatch.spec_days == _spec_days(spec_days))
    keyword_value = (keyword or "").strip()
    if keyword_value:
        conditions.append(RenewalCardKeyBatch.batch_no.ilike(f"%{keyword_value}%"))
    return conditions


async def _load_batch_stats(
    session: AsyncSession,
    batch_ids: list[int],
) -> dict[int, dict[str, int]]:
    rows = (
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
    return {
        int(batch_id): {
            "total": int(total_count or 0),
            "used": int(used_count or 0),
            "voided": int(voided_count or 0),
        }
        for batch_id, total_count, used_count, voided_count in rows
        if batch_id is not None
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
    cards = await _load_copyable_cards(session, ids)
    now = _utcnow()
    lines = [_mark_card_copied(card, now=now, with_meta=with_meta) for card in cards]
    await _increment_batch_counter(session, cards, field="copy_count")
    await append_audit(
        session,
        admin_account_id=admin.id,
        action="renewal.cards.copy",
        target_type="renewal_card_key",
        target_id=",".join(str(item) for item in ids),
        detail={"count": len(cards), "with_meta": with_meta},
    )
    return CopyResult(count=len(cards), total=len(cards), copied_text="\n".join(lines))


async def _load_copyable_cards(
    session: AsyncSession,
    ids: list[int],
) -> list[RenewalCardKey]:
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
    return list(cards)


def _mark_card_copied(
    card: RenewalCardKey,
    *,
    now: dt.datetime,
    with_meta: bool,
) -> str:
    card.copy_status = "copied"
    card.copied_at = now
    if with_meta:
        return f"{card.card_code_plain} | {card.spec_days or '-'}天 | 批次{card.batch_id or '-'}"
    return card.card_code_plain or ""


async def _increment_batch_counter(
    session: AsyncSession,
    cards: list[RenewalCardKey],
    *,
    field: str,
) -> None:
    batch_ids = {card.batch_id for card in cards if card.batch_id}
    if not batch_ids:
        return
    batches = (
        await session.execute(
            select(RenewalCardKeyBatch).where(RenewalCardKeyBatch.id.in_(batch_ids))
        )
    ).scalars().all()
    for batch in batches:
        setattr(batch, field, int(getattr(batch, field)) + 1)


async def void_cards(
    session: AsyncSession,
    *,
    admin: AdminAccount,
    card_ids: list[int],
) -> dict[str, Any]:
    ids = [int(item) for item in card_ids if int(item) > 0]
    if not ids:
        raise ValueError("请选择要作废的卡密")
    cards = await _load_voidable_cards(session, ids)
    changed = _mark_cards_voided(cards, now=_utcnow())
    await append_audit(
        session,
        admin_account_id=admin.id,
        action="renewal.cards.void",
        target_type="renewal_card_key",
        target_id=",".join(str(item) for item in ids),
        detail={"count": len(cards), "changed": changed},
    )
    return {"count": len(cards), "changed": changed}


async def _load_voidable_cards(
    session: AsyncSession,
    ids: list[int],
) -> list[RenewalCardKey]:
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
    return list(cards)


def _mark_cards_voided(cards: list[RenewalCardKey], *, now: dt.datetime) -> int:
    changed = 0
    for card in cards:
        if is_card_voided(card):
            continue
        card.copy_status = "voided"
        card.export_status = "voided"
        card.copied_at = now
        changed += 1
    return changed


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

    await _increment_batch_counter(session, list(cards), field="export_count")

    await append_audit(
        session,
        admin_account_id=admin.id,
        action="renewal.cards.export",
        target_type="renewal_card_key",
        target_id=str(batch_id or "filtered"),
        detail={"count": len(cards), "spec_days": spec_days, "status": status, "keyword": keyword},
    )
    return await serialize_cards(session, cards)
