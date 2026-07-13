from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AdCampaign
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CreateResult

log = structlog.get_logger(__name__)


async def create_ad_campaign(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    *, title: str,
    content: str,
    image_file_id: str | None = None,
    image_url: str | None = None,
    schedule_time: dt.datetime | None = None,
    frequency: str | None = None,
    start_time: dt.datetime | None = None,
    interval_hours: int | None = None,
    max_send_count: int | None = None,
) -> CreateResult:
    try:
        has_image = bool(image_file_id or image_url)
        normalized_start_time = start_time
        normalized_interval_hours = interval_hours

        if normalized_interval_hours and normalized_interval_hours > 0 and normalized_start_time is None:
            normalized_start_time = dt.datetime.now(dt.UTC)

        ad = AdCampaign(
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            title=title,
            content=content,
            image_file_id=image_file_id,
            image_url=image_url,
            has_image=has_image,
            schedule_time=schedule_time,
            frequency=frequency,
            start_time=normalized_start_time,
            interval_hours=normalized_interval_hours,
            max_send_count=max_send_count,
            send_count=0,
            enabled=True,
        )
        session.add(ad)
        await session.flush()
        return CreateResult(success=True, reason="ok", entity=ad, entity_id=ad.id)
    except Exception as exc:
        log.warning("create_ad_campaign_failed", chat_id=chat_id, created_by_user_id=created_by_user_id, error=str(exc))
        return CreateResult(success=False, reason="error")


async def get_chat_ads(
    session: AsyncSession,
    chat_id: int,
    enabled_only: bool = False,
) -> list[AdCampaign]:
    return await ServiceBase._get_list(
        session,
        AdCampaign,
        filters={"chat_id": chat_id},
        active_only=enabled_only,
        order_by="created_at",
        descending=True,
    )


async def get_ad(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    return await ServiceBase._get_by_id(session, AdCampaign, ad_id)


async def delete_ad(
    session: AsyncSession,
    ad_id: int,
) -> bool:
    ad = await get_ad(session, ad_id)
    if not ad:
        return False
    await ServiceBase._delete_entity(session, ad)
    return True


async def toggle_ad(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    ad = await get_ad(session, ad_id)
    if ad:
        await ServiceBase._update_entity(
            session,
            ad,
            {"enabled": not ad.enabled},
        )
    return ad
