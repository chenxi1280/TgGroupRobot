"""Web 管理端静态页与认证路由。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.api_common import bad_request, ok
from backend.features.web_admin.api_models import LoginRequest
from backend.features.web_admin.auth_service import (
    SESSION_COOKIE_NAME,
    login_admin,
    logout_session,
    serialize_admin,
)
from backend.features.web_admin.dependencies import admin_session as db_session
from backend.features.web_admin.dependencies import current_admin
from backend.platform.config.core.settings import Settings
from backend.platform.db.schema.models.core import AdminAccount

STATIC_DIR = Path(__file__).parent / "static"
SECONDS_PER_DAY = 86_400
DEFAULT_SESSION_DAYS = 7

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/", response_class=HTMLResponse)
async def admin_index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "admin.html").read_text(encoding="utf-8"))


@router.get("/admin/static/{filename}")
async def admin_static(filename: str):
    path = (STATIC_DIR / filename).resolve()
    if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "text/css" if filename.endswith(".css") else "application/javascript"
    return FileResponse(path, media_type=media_type)


@router.post("/admin/api/auth/login")
async def api_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    *,
    session: AsyncSession = Depends(db_session),
):
    settings: Settings = request.app.state.settings
    try:
        result = await login_admin(
            session,
            settings,
            username=payload.username,
            password=payload.password,
        )
    except ValueError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        result.token,
        httponly=True,
        samesite="lax",
        max_age=max(int(settings.admin_session_days or DEFAULT_SESSION_DAYS), 1) * SECONDS_PER_DAY,
        path="/admin",
    )
    return ok(serialize_admin(result.account), "登录成功")


@router.get("/admin/api/auth/me")
async def api_me(
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    await session.commit()
    return ok(serialize_admin(admin))


@router.post("/admin/api/auth/logout")
async def api_logout(
    request: Request,
    response: Response,
    admin: AdminAccount = Depends(current_admin),
    *,
    session: AsyncSession = Depends(db_session),
):
    await logout_session(session, request.cookies.get(SESSION_COOKIE_NAME), admin)
    await session.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/admin")
    return ok(message="已退出")
