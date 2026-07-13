"""Web 管理端账号与审计路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.api_common import ok
from backend.features.web_admin.api_models import (
    AdminAccountRequest,
    AdminPasswordRequest,
    CurrentPasswordRequest,
)
from backend.features.web_admin.auth_service import (
    SESSION_COOKIE_NAME,
    append_audit,
    hash_password,
    revoke_admin_sessions,
    serialize_admin,
    verify_password,
)
from backend.features.web_admin.dependencies import admin_session as db_session
from backend.features.web_admin.dependencies import current_admin
from backend.platform.db.schema.models.core import AdminAccount, AdminAuditLog

router = APIRouter()


@router.get("/admin/api/accounts")
async def api_list_accounts(
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    _ = admin
    accounts = (
        await session.execute(select(AdminAccount).order_by(AdminAccount.id.asc()))
    ).scalars().all()
    return ok({"items": [serialize_admin(account) for account in accounts]})


@router.post("/admin/api/accounts")
async def api_create_account(
    payload: AdminAccountRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="后台账号不能为空")
    existing = (
        await session.execute(
            select(AdminAccount).where(AdminAccount.username == username).limit(1)
        )
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
    await _audit_account(
        session,
        admin,
        account,
        action="admin_account.create",
        detail={"username": username},
    )
    await session.commit()
    return ok(serialize_admin(account), "后台账号已创建")


async def _audit_account(
    session: AsyncSession,
    admin: AdminAccount,
    account: AdminAccount,
    *,
    action: str,
    detail: dict,
) -> None:
    await append_audit(
        session,
        admin_account_id=admin.id,
        action=action,
        target_type="admin_account",
        target_id=str(account.id),
        detail=detail,
    )


async def _required_account(session: AsyncSession, account_id: int) -> AdminAccount:
    account = await session.get(AdminAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="后台账号不存在")
    return account


@router.post("/admin/api/accounts/{account_id}/status")
async def api_update_account_status(
    account_id: int,
    status: str,
    admin: AdminAccount = Depends(current_admin),
    *,
    session: AsyncSession = Depends(db_session),
):
    if status not in {"active", "disabled"}:
        raise HTTPException(status_code=400, detail="账号状态无效")
    account = await _required_account(session, account_id)
    if account.id == admin.id and status != "active":
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    account.status = status
    if status == "disabled":
        await revoke_admin_sessions(session, admin_account_id=account.id)
    await _audit_account(
        session,
        admin,
        account,
        action="admin_account.status",
        detail={"status": status},
    )
    await session.commit()
    return ok(serialize_admin(account), "账号状态已更新")


@router.post("/admin/api/accounts/{account_id}/password")
async def api_reset_account_password(
    account_id: int,
    payload: AdminPasswordRequest,
    admin: AdminAccount = Depends(current_admin),
    *,
    session: AsyncSession = Depends(db_session),
):
    account = await _required_account(session, account_id)
    account.password_hash = hash_password(payload.password)
    await revoke_admin_sessions(session, admin_account_id=account.id)
    await _audit_account(
        session,
        admin,
        account,
        action="admin_account.password_reset",
        detail={},
    )
    await session.commit()
    return ok(serialize_admin(account), "账号密码已重置")


@router.post("/admin/api/auth/change-password")
async def api_change_current_password(
    payload: CurrentPasswordRequest,
    request: Request,
    admin: AdminAccount = Depends(current_admin),
    *,
    session: AsyncSession = Depends(db_session),
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
    await _audit_account(
        session,
        admin,
        account,
        action="admin.password_change",
        detail={},
    )
    await session.commit()
    return ok(message="密码已修改")


def _serialize_audit_row(row) -> dict:
    log, username, display_name = row
    return {
        "id": log.id,
        "admin_account_id": log.admin_account_id,
        "admin_text": display_name or username or "",
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "detail": log.detail or {},
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("/admin/api/audit-logs")
async def api_list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: AdminAccount = Depends(current_admin),
    *,
    session: AsyncSession = Depends(db_session),
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
    return ok({"items": [_serialize_audit_row(row) for row in rows], "total": total})
