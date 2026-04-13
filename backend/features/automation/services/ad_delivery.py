from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.automation.services.ad_campaigns import get_ad
from backend.features.automation.services.ad_schedule import should_send_ad
from backend.platform.db.schema.models.core import AdCampaign
from backend.shared.services.base import ServiceBase


async def get_due_ads(
    session: AsyncSession,
) -> list[AdCampaign]:
    ads = await ServiceBase._get_list(
        session,
        AdCampaign,
        active_only=True,
    )
    return [ad for ad in ads if should_send_ad(ad)]


async def mark_ad_sent(
    session: AsyncSession,
    ad_id: int,
) -> bool:
    ad = await get_ad(session, ad_id)
    if not ad:
        return False

    updates: dict[str, object] = {
        "last_sent_at": dt.datetime.now(dt.UTC),
        "send_locked": False,
    }

    if ad.send_count is not None:
        updates["send_count"] = ad.send_count + 1

    next_send_count = (ad.send_count or 0) + 1
    if ad.max_send_count and next_send_count >= ad.max_send_count:
        updates["enabled"] = False

    if not ad.interval_hours and (ad.frequency == "once" or ad.frequency is None):
        updates["enabled"] = False

    await ServiceBase._update_entity(session, ad, updates)
    return True


async def lock_ad_for_sending(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    stmt = (
        select(AdCampaign)
        .where(
            AdCampaign.id == ad_id,
            AdCampaign.enabled == True,
            AdCampaign.send_locked == False,
        )
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    ad = result.scalar_one_or_none()
    if not ad:
        return None

    ad.send_locked = True
    await session.flush()
    return ad
