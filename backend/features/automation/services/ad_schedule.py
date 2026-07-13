from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AdCampaign
from backend.shared.services.base import ServiceBase
_SHOULD_SEND_AD_THRESHOLD_30 = 30
_SHOULD_SEND_AD_THRESHOLD_7 = 7



def is_rotation_ad(ad: AdCampaign) -> bool:
    """判断广告是否属于循环轮播任务。"""
    if ad.interval_hours and ad.interval_hours > 0:
        return True
    return ad.frequency in {"daily", "weekly", "monthly"}


def is_ad_exhausted(ad: AdCampaign) -> bool:
    """判断广告是否已达到最大推送次数。"""
    return bool(ad.max_send_count and (ad.send_count or 0) >= ad.max_send_count)


def get_ad_next_send_time(ad: AdCampaign) -> dt.datetime | None:
    """计算广告下一次理论发送时间。"""
    if not ad.enabled or is_ad_exhausted(ad):
        return None

    base_start = ad.start_time or ad.schedule_time or ad.created_at

    if ad.interval_hours and ad.interval_hours > 0:
        if ad.last_sent_at:
            return ad.last_sent_at + dt.timedelta(hours=ad.interval_hours)
        return base_start

    if ad.frequency in (None, "once"):
        if ad.last_sent_at:
            return None
        return ad.schedule_time or ad.created_at

    if ad.frequency == "daily":
        return (ad.last_sent_at or base_start) + dt.timedelta(days=1) if ad.last_sent_at else base_start
    if ad.frequency == "weekly":
        return (ad.last_sent_at or base_start) + dt.timedelta(days=7) if ad.last_sent_at else base_start
    if ad.frequency == "monthly":
        return (ad.last_sent_at or base_start) + dt.timedelta(days=30) if ad.last_sent_at else base_start

    return None


def should_send_ad(ad: AdCampaign) -> bool:
    if not ad.enabled:
        return False

    now = dt.datetime.now(dt.UTC)

    if ad.interval_hours and ad.interval_hours > 0:
        start_at = ad.start_time or ad.schedule_time or ad.created_at
        if start_at and now < start_at:
            return False

        send_count = ad.send_count or 0
        if ad.max_send_count and send_count >= ad.max_send_count:
            return False

        if ad.last_sent_at:
            next_send_time = ad.last_sent_at + dt.timedelta(hours=ad.interval_hours)
            return now >= next_send_time
        return True

    if ad.schedule_time and now < ad.schedule_time:
        return False

    if ad.frequency in (None, "once"):
        return ad.last_sent_at is None
    if ad.frequency == "daily":
        if ad.last_sent_at:
            return (now - ad.last_sent_at).days >= 1
        return True
    if ad.frequency == "weekly":
        if ad.last_sent_at:
            return (now - ad.last_sent_at).days >= _SHOULD_SEND_AD_THRESHOLD_7
        return True
    if ad.frequency == "monthly":
        if ad.last_sent_at:
            return (now - ad.last_sent_at).days >= _SHOULD_SEND_AD_THRESHOLD_30
        return True

    return ad.last_sent_at is None


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
