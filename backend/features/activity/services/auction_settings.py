from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.auction_time import now_utc
from backend.platform.db.schema.models.expansion import AuctionSetting
from backend.shared.services.module_settings_service import ModuleSettingsService


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> AuctionSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(AuctionSetting, chat_id)
    if setting is None:
        setting = AuctionSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> AuctionSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = now_utc()
    await session.flush()
    return setting
