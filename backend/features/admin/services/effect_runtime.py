"""Single remote attempt with durable send boundary and per-group process exclusion."""
from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from sqlalchemy import text
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from backend.features.admin.services import effect_store as store
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.shared.services.base import ValidationError


@asynccontextmanager
async def group_execution_lock(db, chat_id):
    async with db.engine.connect() as connection:
        acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': chat_id})
        try:
            yield bool(acquired)
        finally:
            if acquired:
                await connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': chat_id})
            await connection.rollback()


async def run_effect(app, effect_id: int, *, chat_id: int, now):
    db = app.bot_data['db']
    async with group_execution_lock(db, chat_id) as acquired:
        if not acquired:
            return 'busy'
        row = await store.claim(db, effect_id, now=now)
        if row is None:
            async with db.session_factory() as session:
                current = await session.get(AdminEffect, effect_id)
                return 'uncertain' if current is not None and current.status == 'uncertain' else 'not_claimed'
        try:
            return await _attempt(app, row, now=now)
        except Exception as exc:
            # Keep a started claim for lease recovery; never turn unknown into a retry.
            import structlog
            structlog.get_logger(__name__).exception('admin_effect_attempt_failed', effect_id=row.id)
            raise RuntimeError(f'administrative effect {row.id} failed: {type(exc).__name__}') from exc


async def _attempt(app, row, *, now):
    from backend.features.admin.services.effect_targets import execute, followups
    db = app.bot_data['db']
    admitted=await _admit(app,row,now=now)
    if admitted is not None:
        return admitted
    await store.mark_started(db, row, now=now)
    try:
        result = await execute(app, row)
    except RetryAfter as exc:
        return await _rate_limit(db,row,exc=exc,now=now)
    except (BadRequest, Forbidden, ValueError, ValidationError) as exc:
        await store.finish(db, row, status='permanent_failed', now=now, error=str(exc))
        return 'permanent_failed'
    except (NetworkError, TelegramError) as exc:
        await store.finish(db, row, status='uncertain', now=now, error=str(exc))
        return 'uncertain'
    await store.finish(db, row, status='succeeded', now=now, result=result, on_success=followups)
    return 'succeeded'


async def _admit(app,row,*,now):
    from backend.features.admin.services.effect_targets import eligible
    db=app.bot_data['db']
    try:
        valid = await eligible(app, row, now=now)
    except (BadRequest,Forbidden,ValidationError,KeyError,TypeError,ValueError) as exc:
        await store.finish(db, row, status='permanent_failed', now=now, error=f'invalid_configuration: {exc}')
        return 'permanent_failed'
    except RetryAfter as exc:
        return await _rate_limit(db,row,exc=exc,now=now)
    except (NetworkError,TelegramError) as exc:
        await store.finish(db,row,status='retryable_failed',now=now,error=f'preflight_read_failed: {exc}')
        return 'retryable_failed'
    if (row.expires_at is not None and row.expires_at <= now) or not valid:
        await store.finish(db, row, status='cancelled', now=now, error='expired_or_configuration_changed')
        return 'cancelled'
    return None


async def _rate_limit(db,row,*,exc,now):
    delay = exc.retry_after.total_seconds() if isinstance(exc.retry_after, dt.timedelta) else exc.retry_after
    await store.finish(db,row,status='retryable_failed',now=now,error='telegram_rate_limited',retry_seconds=delay)
    return 'retryable_failed'


async def run_pending(app, *, now=None, kinds=None, chat_id=None):
    now = now or dt.datetime.now(dt.UTC)
    statuses = []
    for effect_id, chat_id in await store.candidates(app.bot_data['db'], now=now, kinds=kinds, chat_id=chat_id):
        try:
            statuses.append(await run_effect(app, effect_id, chat_id=chat_id, now=now))
        except Exception:
            # The durable claim retains the crash boundary; keep other groups moving.
            statuses.append('attempt_failed')
    if any(state in {'permanent_failed', 'uncertain', 'retryable_failed', 'attempt_failed'} for state in statuses):
        raise RuntimeError('administrative effects include failures; inspect durable history')
    return statuses
