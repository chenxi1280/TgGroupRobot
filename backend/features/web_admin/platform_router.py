"""Web 管理端公告与平台配置路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.announcement_service import (
    get_announcement_settings,
    update_announcement_settings,
)
from backend.features.web_admin.api_common import (
    PLATFORM_CONFIG_KEYS,
    bad_request,
    ok,
    settings_dict,
    upsert_settings,
)
from backend.features.web_admin.api_models import AnnouncementRequest, PlatformConfigRequest
from backend.features.web_admin.auth_service import append_audit
from backend.features.web_admin.dependencies import admin_session as db_session
from backend.features.web_admin.dependencies import current_admin
from backend.platform.db.schema.models.core import AdminAccount

router = APIRouter()


@router.get("/admin/api/announcement")
async def api_get_announcement(
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    _ = admin
    return ok(await get_announcement_settings(session))


@router.put("/admin/api/announcement")
async def api_update_announcement(
    payload: AnnouncementRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    try:
        data = await update_announcement_settings(
            session,
            admin=admin,
            enabled=payload.enabled,
            entry_text=payload.entry_text,
            target_url=payload.target_url,
            message_text=payload.message_text,
        )
    except ValueError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return ok(data, "公告栏配置已保存")


@router.get("/admin/api/platform-config")
async def api_get_platform_config(
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    _ = admin
    return ok(await settings_dict(session, PLATFORM_CONFIG_KEYS))


@router.put("/admin/api/platform-config")
async def api_update_platform_config(
    payload: PlatformConfigRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    values = {
        PLATFORM_CONFIG_KEYS[key]: str(value or "").strip()
        for key, value in payload.model_dump().items()
    }
    await upsert_settings(session, values)
    await append_audit(
        session,
        admin_account_id=admin.id,
        action="platform_config.update",
        target_type="app_settings",
        target_id="platform_config",
        detail=payload.model_dump(),
    )
    await session.commit()
    data = await settings_dict(session, PLATFORM_CONFIG_KEYS)
    return ok(data, "平台公共配置已保存")
