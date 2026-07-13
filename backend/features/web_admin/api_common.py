"""Web 管理端通用响应与配置持久化。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AppSetting

PLATFORM_CONFIG_KEYS = {
    "platform_name": "platform_name",
    "bot_display_name": "bot_display_name",
    "web_admin_title": "web_admin_title",
    "maintenance_notice": "maintenance_notice",
    "contact_text": "contact_text",
    "help_text": "help_text",
}


def ok(data=None, message: str = "ok") -> dict:
    return {"success": True, "message": message, "data": data}


def bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def settings_dict(session: AsyncSession, keys: dict[str, str]) -> dict[str, str]:
    rows = (
        await session.execute(select(AppSetting).where(AppSetting.key.in_(keys.values())))
    ).scalars().all()
    by_key = {row.key: row.value for row in rows}
    return {name: by_key.get(setting_key, "") for name, setting_key in keys.items()}


async def upsert_settings(session: AsyncSession, values: dict[str, str]) -> None:
    for key, value in values.items():
        item = await session.get(AppSetting, key)
        if item is None:
            session.add(AppSetting(key=key, value=value))
        else:
            item.value = value
    await session.flush()
