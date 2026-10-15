"""Stable identities and explicit outcome transitions; no remote work in planning."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from backend.platform.db.schema.models.admin_effects import AdminEffect

BATCH_SIZE = 100
LEASE_SECONDS = 120
MAX_ATTEMPTS = 5
RETRY_SECONDS = 60


def identity(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


async def enqueue(session, *, key: str, chat_id: int, kind: str, payload: dict, due, expires=None):
    result = await session.execute(insert(AdminEffect).values(effect_key=key, chat_id=chat_id,
        kind=kind, payload=payload, status='pending', attempts=0, next_run_at=due,
        expires_at=expires, result={}).on_conflict_do_nothing(index_elements=['effect_key']).returning(AdminEffect.id))
    return result.scalar_one_or_none()


async def candidates(db, *, now, kinds=None, chat_id=None):
    query = select(AdminEffect.id, AdminEffect.chat_id).where(
        or_(AdminEffect.status.in_(['pending', 'retryable_failed']),
            (AdminEffect.status == 'processing') & (AdminEffect.lease_until <= now)),
        AdminEffect.next_run_at <= now,
    ).order_by(AdminEffect.next_run_at, AdminEffect.id).limit(BATCH_SIZE)
    if chat_id is not None:
        query = query.where(AdminEffect.chat_id == chat_id)
    if kinds:
        query = query.where(AdminEffect.kind.in_(kinds))
    async with db.session_factory() as session:
        return list((await session.execute(query)).all())


async def claim(db, effect_id: int, *, now):
    async with db.session_factory() as session:
        row = await session.get(AdminEffect, effect_id, with_for_update=True)
        if row is None or row.next_run_at > now:
            return None
        if row.status == 'processing' and row.lease_until <= now:
            row.status = 'uncertain' if row.started_at else 'pending'
            row.error = 'lease_expired_after_remote_start' if row.started_at else 'lease_expired_before_remote_start'
        if row.status not in {'pending', 'retryable_failed'}:
            if row.status=='uncertain' and row.kind=='delivery_action':
                from backend.features.automation.delivery_action_journal import finalize_action
                await finalize_action(session,row)
            await session.commit()
            return None
        row.status, row.started_at = 'processing', None
        row.attempts += 1
        row.lease_until = now + dt.timedelta(seconds=LEASE_SECONDS)
        await session.commit()
        return row


async def mark_started(db, row, *, now):
    async with db.session_factory() as session:
        live = await session.get(AdminEffect, row.id, with_for_update=True)
        if live.status != 'processing' or live.attempts != row.attempts:
            raise RuntimeError('administrative effect claim lost')
        live.started_at = now
        await session.commit()


async def finish(db, row, *, status: str, now, result=None, error=None, retry_seconds=RETRY_SECONDS, on_success=None):
    async with db.session_factory() as session:
        live = await session.get(AdminEffect, row.id, with_for_update=True)
        if live.status != 'processing' or live.attempts != row.attempts:
            raise RuntimeError('administrative effect completion claim lost')
        if status == 'retryable_failed' and live.attempts >= MAX_ATTEMPTS:
            status = 'permanent_failed'
        live.status, live.error, live.result = status, error, result or {}
        live.lease_until = None
        if status == 'retryable_failed':
            live.next_run_at = now + dt.timedelta(seconds=retry_seconds)
        else:
            live.completed_at = now
        if status == 'succeeded' and on_success is not None:
            await on_success(session, live, now=now)
        if live.kind == 'delivery_action':
            from backend.features.automation.delivery_action_journal import finalize_action
            await finalize_action(session, live)
        await session.commit()
