from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.announcement_service import (
    get_announcement_settings,
    update_announcement_settings,
)
from backend.features.web_admin.auth_service import (
    SESSION_COOKIE_NAME,
    get_account_by_session_token,
    login_admin,
    logout_session,
    serialize_admin,
)
from backend.features.web_admin.card_service import (
    COPY_CARD_LIMIT,
    KEY_SPECS,
    copy_cards,
    generate_card_batch,
    list_batches,
    list_cards,
    rows_for_export,
)
from backend.platform.config.core.settings import Settings
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import AdminAccount


STATIC_DIR = Path(__file__).parent / "static"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class GenerateBatchRequest(BaseModel):
    spec_days: int
    quantity: int = Field(..., ge=1, le=500)


class CopyCardsRequest(BaseModel):
    card_ids: list[int] = Field(..., min_length=1, max_length=COPY_CARD_LIMIT)
    with_meta: bool = False


class AnnouncementRequest(BaseModel):
    enabled: bool = True
    entry_text: str = Field(default="", max_length=500)
    target_url: str = Field(default="", max_length=500)
    message_text: str = Field(default="", max_length=2000)


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.session_factory() as session:
        yield session


async def _current_admin(
    request: Request,
    session: AsyncSession = Depends(_session),
) -> AdminAccount:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    account = await get_account_by_session_token(session, token)
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录后台")
    return account


def _ok(data=None, message: str = "ok") -> dict:
    return {"success": True, "message": message, "data": data}


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def create_admin_web_app(db: Database, settings: Settings) -> FastAPI:
    app = FastAPI(title="TgGroupRobot Admin", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.settings = settings

    @app.get("/admin", response_class=HTMLResponse)
    @app.get("/admin/", response_class=HTMLResponse)
    async def admin_index() -> HTMLResponse:
        html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/admin/static/{filename}")
    async def admin_static(filename: str):
        path = (STATIC_DIR / filename).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        media_type = "text/css" if filename.endswith(".css") else "application/javascript"
        return FileResponse(path, media_type=media_type)

    @app.post("/admin/api/auth/login")
    async def api_login(payload: LoginRequest, response: Response, session: AsyncSession = Depends(_session)):
        try:
            result = await login_admin(
                session,
                settings,
                username=payload.username,
                password=payload.password,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        await session.commit()
        response.set_cookie(
            SESSION_COOKIE_NAME,
            result.token,
            httponly=True,
            samesite="lax",
            max_age=max(int(settings.admin_session_days or 7), 1) * 86400,
            path="/admin",
        )
        return _ok(serialize_admin(result.account), "登录成功")

    @app.get("/admin/api/auth/me")
    async def api_me(admin: AdminAccount = Depends(_current_admin), session: AsyncSession = Depends(_session)):
        await session.commit()
        return _ok(serialize_admin(admin))

    @app.post("/admin/api/auth/logout")
    async def api_logout(
        request: Request,
        response: Response,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        await logout_session(session, request.cookies.get(SESSION_COOKIE_NAME), admin)
        await session.commit()
        response.delete_cookie(SESSION_COOKIE_NAME, path="/admin")
        return _ok(message="已退出")

    @app.get("/admin/api/key-specs")
    async def api_key_specs(admin: AdminAccount = Depends(_current_admin)):
        return _ok({"items": KEY_SPECS, "copy_limit": COPY_CARD_LIMIT})

    @app.post("/admin/api/key-batches")
    async def api_generate_batch(
        payload: GenerateBatchRequest,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        try:
            data = await generate_card_batch(
                session,
                admin=admin,
                spec_days=payload.spec_days,
                quantity=payload.quantity,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        await session.commit()
        return _ok(data, "卡密批次已生成")

    @app.get("/admin/api/key-batches")
    async def api_list_batches(
        spec_days: int | None = None,
        keyword: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        _ = admin
        try:
            data = await list_batches(session, spec_days=spec_days, keyword=keyword, limit=limit, offset=offset)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return _ok(data)

    @app.get("/admin/api/keys")
    async def api_list_keys(
        spec_days: int | None = None,
        batch_id: int | None = None,
        status: str | None = None,
        keyword: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        _ = admin
        try:
            data = await list_cards(
                session,
                spec_days=spec_days,
                batch_id=batch_id,
                status=status,
                keyword=keyword,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return _ok(data)

    @app.post("/admin/api/keys/copy")
    async def api_copy_keys(
        payload: CopyCardsRequest,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        try:
            result = await copy_cards(
                session,
                admin=admin,
                card_ids=payload.card_ids,
                with_meta=payload.with_meta,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        await session.commit()
        return _ok({
            "count": result.count,
            "total": result.total,
            "copied_text": result.copied_text,
            "truncated": result.truncated,
        })

    @app.get("/admin/api/keys/export")
    async def api_export_keys(
        spec_days: int | None = None,
        batch_id: int | None = None,
        status: str | None = None,
        keyword: str | None = None,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        rows = await rows_for_export(
            session,
            admin=admin,
            spec_days=spec_days,
            batch_id=batch_id,
            status=status,
            keyword=keyword,
        )
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="缺少 openpyxl 依赖，无法导出 XLSX") from exc

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "续费卡密"
        sheet.append([
            "卡密",
            "规格天数",
            "状态",
            "激活群组",
            "激活用户",
            "群主",
            "激活时间",
            "创建时间",
        ])
        for row in rows:
            sheet.append([
                row.get("card_code") or "历史卡密无明文",
                row.get("spec_days") or "",
                "已激活" if row.get("used") else "可用",
                row.get("used_by_chat_title") or "",
                row.get("used_by_user_text") or "",
                row.get("owner_text") or "",
                row.get("used_at") or "",
                row.get("created_at") or "",
            ])
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        await session.commit()
        headers = {"Content-Disposition": "attachment; filename=renewal-keys.xlsx"}
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    @app.get("/admin/api/announcement")
    async def api_get_announcement(
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        _ = admin
        return _ok(await get_announcement_settings(session))

    @app.put("/admin/api/announcement")
    async def api_update_announcement(
        payload: AnnouncementRequest,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
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
            raise _bad_request(exc) from exc
        await session.commit()
        return _ok(data, "公告栏配置已保存")

    return app
