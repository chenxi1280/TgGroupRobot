from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AdCampaign
from backend.shared.services.base import ServiceBase
_FREQUENCY_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}



def is_rotation_ad(ad: AdCampaign) -> bool:
    """判断广告是否属于循环轮播任务。"""
    if ad.interval_hours and ad.interval_hours > 0:
        return True
    return ad.frequency in {"daily", "weekly", "monthly"}


def is_ad_exhausted(ad: AdCampaign) -> bool:
    """判断广告是否已达到最大推送次数。"""
    return bool(ad.max_send_count and (ad.send_count or 0) >= ad.max_send_count)


def _frequency_next_send_time(ad: AdCampaign, base_start: dt.datetime) -> dt.datetime | None:
    if ad.frequency in (None, "once"):
        return None if ad.last_sent_at else ad.schedule_time or ad.created_at
    days = _FREQUENCY_DAYS.get(ad.frequency)
    if days is None:
        return None
    return ad.last_sent_at + dt.timedelta(days=days) if ad.last_sent_at else base_start


def get_ad_next_send_time(ad: AdCampaign) -> dt.datetime | None:
    """计算广告下一次理论发送时间。"""
    if not ad.enabled or is_ad_exhausted(ad):
        return None

    base_start = ad.start_time or ad.schedule_time or ad.created_at

    if ad.interval_hours and ad.interval_hours > 0:
        if ad.last_sent_at:
            return ad.last_sent_at + dt.timedelta(hours=ad.interval_hours)
        return base_start

    return _frequency_next_send_time(ad, base_start)


def _rotation_due(ad: AdCampaign, now: dt.datetime) -> bool:
    start_at = ad.start_time or ad.schedule_time or ad.created_at
    if start_at and now < start_at:
        return False
    if is_ad_exhausted(ad):
        return False
    if not ad.last_sent_at:
        return True
    next_send_time = ad.last_sent_at + dt.timedelta(hours=ad.interval_hours)
    return now >= next_send_time


def should_send_ad(ad: AdCampaign) -> bool:
    if not ad.enabled:
        return False

    now = dt.datetime.now(dt.UTC)

    if ad.interval_hours and ad.interval_hours > 0:
        return _rotation_due(ad, now)

    if ad.schedule_time and now < ad.schedule_time:
        return False

    if ad.frequency in (None, "once"):
        return ad.last_sent_at is None
    days = _FREQUENCY_DAYS.get(ad.frequency)
    if days is None or ad.last_sent_at is None:
        return ad.last_sent_at is None
    return (now - ad.last_sent_at).days >= days


async def get_scheduled_ads(session: AsyncSession) -> list[AdCampaign]:
    ads = await ServiceBase._get_list(
        session,
        AdCampaign,
        active_only=True,
    )
    return [
        ad for ad in ads
        if ad.start_time is not None or ad.schedule_time is not None or ad.interval_hours is not None
    ]
