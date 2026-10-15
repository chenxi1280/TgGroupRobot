"""Durable boundary identities shared by scheduler and group-message paths."""
from __future__ import annotations

import datetime as dt
from sqlalchemy import select, update
from backend.features.admin.services.effect_store import enqueue, identity
from backend.features.group_ops.services.group_permission_profiles import profile_permissions, profile_values
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.platform.db.schema.models.chat import ChatSettings
from backend.shared.services.module_config_service import get_module_config
from backend.shared.time_helper import LOCAL_TIMEZONE

PHRASE_VALID_SECONDS = 300


def schedule_spec(settings, *, now):
    if not settings.group_lock_schedule_enabled:
        return None
    from backend.features.group_ops.group_hooks.control_lock import _get_group_lock_schedule_times
    opening, closing = _get_group_lock_schedule_times(settings)
    try:
        open_at = dt.time.fromisoformat(opening or '')
        close_at = dt.time.fromisoformat(closing or '')
    except ValueError:
        return None
    if open_at == close_at:
        return None
    local = now.astimezone(LOCAL_TIMEZONE)
    times = _boundaries(local, open_at=open_at, close_at=close_at)
    boundary, closed = max((x for x in times if x[0] <= local), key=lambda x:x[0])
    expiry = min(x[0] for x in times if x[0] > local)
    payload = lock_payload(settings, closed=closed)
    payload.update(source='schedule', boundary=boundary.isoformat())
    key = identity('group_lock', settings.chat_id, boundary, payload['permissions'])
    return key, payload, expiry


def _boundaries(local, *, open_at, close_at):
    times = [(dt.datetime.combine(local.date()+dt.timedelta(days=offset), hour, LOCAL_TIMEZONE), closed)
             for offset in (-1, 0, 1) for hour, closed in ((open_at, False), (close_at, True))]
    return times


def lock_payload(settings, *, closed: bool):
    config = get_module_config(settings, 'group_lock')
    return {'closed': closed, 'permissions': profile_permissions(settings, closed=closed).to_dict(),
            'independent': profile_values(settings, closed=closed) is not None,
            'notice': config.get('notices', {}).get('closed' if closed else 'open', {})}


async def plan_schedule(db, *, now, chat_id=None):
    async with db.session_factory() as session:
        query = select(ChatSettings).where(ChatSettings.group_lock_schedule_enabled.is_(True)).order_by(ChatSettings.chat_id)
        if chat_id is not None:
            query = query.where(ChatSettings.chat_id == chat_id)
        settings = list((await session.scalars(query)).all())
        ids = []
        for item in settings:
            spec = schedule_spec(item, now=now)
            if spec:
                ids.append(await _plan_one(session, item, spec=spec, now=now))
        await session.commit()
    return [item for item in ids if item is not None]


async def _plan_one(session, settings, *, spec, now):
    key, payload, expiry = spec
    await session.execute(update(AdminEffect).where(AdminEffect.chat_id == settings.chat_id,
        AdminEffect.kind == 'group_lock', AdminEffect.status.in_(['pending', 'retryable_failed']),
        AdminEffect.effect_key != key).values(status='cancelled', error='superseded_schedule', completed_at=now))
    return await enqueue(session, key=key, chat_id=settings.chat_id, kind='group_lock',
                         payload=payload, due=now, expires=expiry)


async def plan_phrase(db, *, chat_id: int, message_id: int, closed: bool, now, user_id: int):
    async with db.session_factory() as session:
        settings = await session.get(ChatSettings, chat_id)
        payload = lock_payload(settings, closed=closed)
        payload.update(source='phrase', actor_id=user_id)
        key = identity('group_phrase', chat_id, message_id)
        await session.execute(update(AdminEffect).where(AdminEffect.chat_id == chat_id,
            AdminEffect.kind == 'group_lock', AdminEffect.status.in_(['pending', 'retryable_failed']),
            AdminEffect.effect_key != key).values(status='cancelled', error='superseded_by_phrase', completed_at=now))
        new_id = await enqueue(session, key=key, chat_id=chat_id, kind='group_lock', payload=payload, due=now,
                               expires=now+dt.timedelta(seconds=PHRASE_VALID_SECONDS))
        effect_id = new_id or await session.scalar(select(AdminEffect.id).where(AdminEffect.effect_key == key))
        await session.commit()
    return effect_id


def valid_lock(row, settings, *, now) -> bool:
    if settings is None:
        return False
    payload = row.payload
    if payload['source'] == 'schedule':
        spec = schedule_spec(settings, now=now)
        return spec is not None and spec[0] == row.effect_key
    return bool(settings.group_lock_phrase_enabled) and payload['permissions'] == lock_payload(settings, closed=payload['closed'])['permissions']
