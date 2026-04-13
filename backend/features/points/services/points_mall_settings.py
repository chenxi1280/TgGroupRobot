from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import PointsMallSetting

UNSET = object()


class PointsMallSettingsMixin:
    @staticmethod
    async def get_or_create_mall_setting(session: AsyncSession, chat_id: int) -> PointsMallSetting:
        result = await session.execute(select(PointsMallSetting).where(PointsMallSetting.chat_id == chat_id))
        setting = result.scalar_one_or_none()
        if setting is None:
            setting = PointsMallSetting(chat_id=chat_id)
            session.add(setting)
            await session.flush()
        return setting

    @staticmethod
    async def update_mall_setting(
        session: AsyncSession,
        setting: PointsMallSetting,
        *,
        enabled: bool | None = None,
        auto_unlist_when_out_of_stock: bool | None = None,
        entry_command: str | None = None,
        redeem_notice_delete_seconds: int | None = None,
        cover_media_type: str | None | Any = UNSET,
        cover_file_id: str | None | Any = UNSET,
    ) -> PointsMallSetting:
        if enabled is not None:
            setting.enabled = enabled
        if auto_unlist_when_out_of_stock is not None:
            setting.auto_unlist_when_out_of_stock = auto_unlist_when_out_of_stock
        if entry_command is not None:
            setting.entry_command = entry_command
        if redeem_notice_delete_seconds is not None:
            setting.redeem_notice_delete_seconds = max(int(redeem_notice_delete_seconds), 0)
        if cover_media_type is not UNSET or cover_file_id is not UNSET:
            setting.cover_media_type = cover_media_type
            setting.cover_file_id = cover_file_id
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting
