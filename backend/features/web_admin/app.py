from __future__ import annotations

from io import BytesIO
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.announcement_service import (
    get_announcement_settings,
    update_announcement_settings,
)
from backend.features.web_admin.auth_service import (
    SESSION_COOKIE_NAME,
    append_audit,
    hash_password,
    login_admin,
    logout_session,
    revoke_admin_sessions,
    serialize_admin,
    verify_password,
)
from backend.features.web_admin.card_service import (
    COPY_CARD_LIMIT,
    KEY_SPECS,
    copy_cards,
    generate_card_batch,
    list_batches,
    list_cards,
    rows_for_export,
    void_cards,
)
from backend.features.web_admin.dependencies import admin_session as _session
from backend.features.web_admin.dependencies import current_admin as _current_admin
from backend.features.web_admin.verification_timeout_router import router as verification_timeout_router
from backend.features.web_admin.ad_delivery_router import router as ad_delivery_router
from backend.platform.config.core.settings import Settings
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import AdminAccount, AdminAuditLog, AppSetting


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


class VoidCardsRequest(BaseModel):
    card_ids: list[int] = Field(..., min_length=1, max_length=500)


class AnnouncementRequest(BaseModel):
    enabled: bool = True
    entry_text: str = Field(default="", max_length=500)
    target_url: str = Field(default="", max_length=500)
    message_text: str = Field(default="", max_length=2000)


class PlatformConfigRequest(BaseModel):
    platform_name: str = Field(default="", max_length=80)
    bot_display_name: str = Field(default="", max_length=80)
    web_admin_title: str = Field(default="", max_length=80)
    maintenance_notice: str = Field(default="", max_length=500)
    contact_text: str = Field(default="", max_length=200)
    help_text: str = Field(default="", max_length=1000)


class AdminAccountRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=64)


class AdminPasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class CurrentPasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


PLATFORM_CONFIG_KEYS = {
    "platform_name": "platform_name",
    "bot_display_name": "bot_display_name",
    "web_admin_title": "web_admin_title",
    "maintenance_notice": "maintenance_notice",
    "contact_text": "contact_text",
    "help_text": "help_text",
}


def _ok(data=None, message: str = "ok") -> dict:
    return {"success": True, "message": message, "data": data}


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _settings_dict(session: AsyncSession, keys: dict[str, str]) -> dict[str, str]:
    rows = (
        await session.execute(select(AppSetting).where(AppSetting.key.in_(keys.values())))
    ).scalars().all()
    by_key = {row.key: row.value for row in rows}
    return {name: by_key.get(setting_key, "") for name, setting_key in keys.items()}


async def _upsert_settings(session: AsyncSession, values: dict[str, str]) -> None:
    for key, value in values.items():
        item = await session.get(AppSetting, key)
        if item is None:
            session.add(AppSetting(key=key, value=value))
        else:
            item.value = value
    await session.flush()


def create_admin_web_app(db: Database, settings: Settings) -> FastAPI:
    app = FastAPI(title="TgGroupRobot Admin", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.settings = settings
    app.include_router(verification_timeout_router)
    app.include_router(ad_delivery_router)

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

    @app.post("/admin/api/keys/void")
    async def api_void_keys(
        payload: VoidCardsRequest,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        try:
            result = await void_cards(session, admin=admin, card_ids=payload.card_ids)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        await session.commit()
        return _ok(result, "卡密已作废")

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
                "已作废" if row.get("voided") else ("已激活" if row.get("used") else "可用"),
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

    @app.get("/admin/api/platform-config")
    async def api_get_platform_config(
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        _ = admin
        return _ok(await _settings_dict(session, PLATFORM_CONFIG_KEYS))

    @app.put("/admin/api/platform-config")
    async def api_update_platform_config(
        payload: PlatformConfigRequest,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        values = {
            PLATFORM_CONFIG_KEYS[key]: str(value or "").strip()
            for key, value in payload.model_dump().items()
        }
        await _upsert_settings(session, values)
        await append_audit(
            session,
            admin_account_id=admin.id,
            action="platform_config.update",
            target_type="app_settings",
            target_id="platform_config",
            detail=payload.model_dump(),
        )
        await session.commit()
        return _ok(await _settings_dict(session, PLATFORM_CONFIG_KEYS), "平台公共配置已保存")

    @app.get("/admin/api/accounts")
    async def api_list_accounts(
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        _ = admin
        accounts = (
            await session.execute(select(AdminAccount).order_by(AdminAccount.id.asc()))
        ).scalars().all()
        return _ok({"items": [serialize_admin(account) for account in accounts]})

    @app.post("/admin/api/accounts")
    async def api_create_account(
        payload: AdminAccountRequest,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        username = payload.username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="后台账号不能为空")
        existing = (
            await session.execute(select(AdminAccount).where(AdminAccount.username == username).limit(1))
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=400, detail="后台账号已存在")
        account = AdminAccount(
            username=username,
            password_hash=hash_password(payload.password),
            display_name=(payload.display_name.strip() or username),
            status="active",
        )
        session.add(account)
        await session.flush()
        await append_audit(
            session,
            admin_account_id=admin.id,
            action="admin_account.create",
            target_type="admin_account",
            target_id=str(account.id),
            detail={"username": username},
        )
        await session.commit()
        return _ok(serialize_admin(account), "后台账号已创建")

    @app.post("/admin/api/accounts/{account_id}/status")
    async def api_update_account_status(
        account_id: int,
        status: str,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        if status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail="账号状态无效")
        account = await session.get(AdminAccount, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="后台账号不存在")
        if account.id == admin.id and status != "active":
            raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
        account.status = status
        if status == "disabled":
            await revoke_admin_sessions(session, admin_account_id=account.id)
        await append_audit(
            session,
            admin_account_id=admin.id,
            action="admin_account.status",
            target_type="admin_account",
            target_id=str(account.id),
            detail={"status": status},
        )
        await session.commit()
        return _ok(serialize_admin(account), "账号状态已更新")

    @app.post("/admin/api/accounts/{account_id}/password")
    async def api_reset_account_password(
        account_id: int,
        payload: AdminPasswordRequest,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        account = await session.get(AdminAccount, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="后台账号不存在")
        account.password_hash = hash_password(payload.password)
        await revoke_admin_sessions(session, admin_account_id=account.id)
        await append_audit(
            session,
            admin_account_id=admin.id,
            action="admin_account.password_reset",
            target_type="admin_account",
            target_id=str(account.id),
            detail={},
        )
        await session.commit()
        return _ok(serialize_admin(account), "账号密码已重置")

    @app.post("/admin/api/auth/change-password")
    async def api_change_current_password(
        payload: CurrentPasswordRequest,
        request: Request,
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        account = await session.get(AdminAccount, admin.id)
        if account is None or not verify_password(payload.old_password, account.password_hash):
            raise HTTPException(status_code=400, detail="原密码错误")
        account.password_hash = hash_password(payload.new_password)
        await revoke_admin_sessions(
            session,
            admin_account_id=admin.id,
            except_token=request.cookies.get(SESSION_COOKIE_NAME),
        )
        await append_audit(
            session,
            admin_account_id=admin.id,
            action="admin.password_change",
            target_type="admin_account",
            target_id=str(admin.id),
            detail={},
        )
        await session.commit()
        return _ok(message="密码已修改")

    @app.get("/admin/api/audit-logs")
    async def api_list_audit_logs(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        admin: AdminAccount = Depends(_current_admin),
        session: AsyncSession = Depends(_session),
    ):
        _ = admin
        total = int((await session.execute(select(func.count(AdminAuditLog.id)))).scalar() or 0)
        rows = (
            await session.execute(
                select(AdminAuditLog, AdminAccount.username, AdminAccount.display_name)
                .outerjoin(AdminAccount, AdminAccount.id == AdminAuditLog.admin_account_id)
                .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        items = []
        for log, username, display_name in rows:
            items.append({
                "id": log.id,
                "admin_account_id": log.admin_account_id,
                "admin_text": display_name or username or "",
                "action": log.action,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "detail": log.detail or {},
                "created_at": log.created_at.isoformat() if log.created_at else None,
            })
        return _ok({"items": items, "total": total})

    return app
