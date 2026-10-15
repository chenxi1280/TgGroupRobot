"""Consent-bound private expiry reminders, planned independently of ad dispatch."""
from __future__ import annotations

import datetime as dt
from sqlalchemy import select
from backend.features.admin.services.effect_store import enqueue, identity
from backend.platform.db.schema.models.admin_effects import AdminEffect, NoticeConsent
from backend.platform.db.schema.models.automation import AdCampaign
from backend.shared.time_helper import LOCAL_TIMEZONE

DEFAULT_TEXT = '广告 {title} 将于 {expiry} 到期。群：{chat_id}；编号：{ad_id}。'
DEFAULTS = {'enabled': False, 'advance_days': 3, 'time': '10:00', 'text': DEFAULT_TEXT}


def reminder_spec(ad, consent, *, now):
    config = {**DEFAULTS, **(ad.expiry_notice or {})}
    if not _active(ad, consent, config=config, now=now):
        return None
    local = now.astimezone(LOCAL_TIMEZONE)
    expiry = ad.end_time.astimezone(LOCAL_TIMEZONE)
    days_left = (expiry.date() - local.date()).days
    if days_left < 0 or days_left > config['advance_days']:
        return None
    clock = dt.time.fromisoformat(config['time'])
    due = dt.datetime.combine(local.date(), clock, LOCAL_TIMEZONE).astimezone(dt.UTC)
    end_of_day = dt.datetime.combine(local.date()+dt.timedelta(days=1), dt.time.min, LOCAL_TIMEZONE).astimezone(dt.UTC)
    if due >= min(end_of_day, ad.end_time):
        return None
    key = identity('ad_expiry', ad.id, ad.end_time, consent.user_id, consent.version, local.date())
    payload = {'ad_id': ad.id, 'recipient': consent.user_id, 'consent_version': consent.version,
               'expiry': ad.end_time.isoformat(), 'config': config, 'date': local.date().isoformat()}
    return key, payload, due, min(end_of_day, ad.end_time)


def _active(ad, consent, *, config, now):
    return (config['enabled'] and ad.enabled and ad.end_time is not None and ad.end_time > now
            and consent is not None and consent.enabled and config.get('recipient') == consent.user_id)


async def plan_reminders(db, *, now):
    async with db.session_factory() as session:
        ads = list((await session.scalars(select(AdCampaign).where(AdCampaign.end_time > now).order_by(AdCampaign.id))).all())
        count = 0
        for ad in ads:
            recipient = (ad.expiry_notice or {}).get('recipient')
            consent = await session.get(NoticeConsent, (ad.chat_id, ad.id, recipient)) if recipient else None
            spec = reminder_spec(ad, consent, now=now)
            if spec:
                count += await _plan_one(session, ad, spec=spec)
        await cancel_obsolete(session, now=now)
        await session.commit()
    return count


async def _plan_one(session, ad, *, spec):
    key, payload, due, expiry = spec
    effect_id = await enqueue(session, key=key, chat_id=ad.chat_id, kind='ad_expiry',
                              payload=payload, due=due, expires=expiry)
    if effect_id:
        return 1
    old = await session.scalar(select(AdminEffect).where(AdminEffect.effect_key == key).with_for_update())
    if _refreshable(old):
        old.payload, old.next_run_at, old.expires_at = payload, due, expiry
        old.status, old.completed_at = 'pending', None
    return 0


async def valid_reminder(session, row, *, now):
    ad = await session.get(AdCampaign, row.payload['ad_id'])
    if ad is None or ad.chat_id != row.chat_id:
        return False
    consent = await session.get(NoticeConsent, (row.chat_id, ad.id, row.payload['recipient']))
    spec = reminder_spec(ad, consent, now=now)
    return spec is not None and spec[0] == row.effect_key and spec[1] == row.payload


def _refreshable(row):
    allowed = row.status in {'pending','retryable_failed'} or (
        row.status == 'cancelled' and row.error == 'expired_or_configuration_changed')
    return allowed and row.started_at is None


async def cancel_obsolete(session, *, now):
    rows = list((await session.scalars(select(AdminEffect).where(AdminEffect.kind == 'ad_expiry',
        AdminEffect.status.in_(['pending','retryable_failed'])).order_by(AdminEffect.id).with_for_update())).all())
    for row in rows:
        if not await valid_reminder(session, row, now=now):
            row.status, row.error, row.completed_at = 'cancelled', 'expired_or_configuration_changed', now
