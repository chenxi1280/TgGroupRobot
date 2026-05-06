from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.config.core.settings import Settings
from backend.platform.db.schema.models.core import AdminAccount, AdminAuditLog, AdminSession


SESSION_COOKIE_NAME = "tgg_admin_session"
_PBKDF2_ITERATIONS = 260_000
log = structlog.get_logger(__name__)


@dataclass(slots=True)
class AdminSessionResult:
    token: str
    account: AdminAccount


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        (password or "").encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = (password_hash or "").split("$", 3)
        iterations = int(iterations_raw)
    except (TypeError, ValueError):
        log.warning("admin_password_hash_parse_failed", password_hash=password_hash)
        return False
    if algorithm != "pbkdf2_sha256" or iterations <= 0:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        (password or "").encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual, expected)


async def ensure_bootstrap_admin(session: AsyncSession, settings: Settings) -> AdminAccount | None:
    result = await session.execute(
        select(AdminAccount)
        .order_by(AdminAccount.id.asc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    username = (settings.admin_bootstrap_username or "").strip()
    password = (settings.admin_bootstrap_password or "").strip()
    if not username or not password:
        return None
    if len(password) < 6:
        return None

    account = AdminAccount(
        username=username,
        password_hash=hash_password(password),
        display_name=(settings.admin_bootstrap_display_name or username).strip() or username,
        status="active",
    )
    session.add(account)
    await session.flush()
    await append_audit(
        session,
        admin_account_id=account.id,
        action="admin.bootstrap",
        target_type="admin_account",
        target_id=str(account.id),
        detail={"username": account.username},
    )
    return account


async def login_admin(
    session: AsyncSession,
    settings: Settings,
    *,
    username: str,
    password: str,
) -> AdminSessionResult:
    await ensure_bootstrap_admin(session, settings)
    result = await session.execute(
        select(AdminAccount)
        .where(AdminAccount.username == (username or "").strip())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account is None or account.status != "active" or not verify_password(password, account.password_hash):
        raise ValueError("后台用户名或密码错误")

    token = secrets.token_urlsafe(48)
    now = _utcnow()
    session_days = max(int(settings.admin_session_days or 7), 1)
    account.last_login_at = now
    admin_session = AdminSession(
        token_hash=hash_token(token),
        admin_account_id=account.id,
        expires_at=now + dt.timedelta(days=session_days),
        created_at=now,
        last_seen_at=now,
    )
    session.add(admin_session)
    await append_audit(
        session,
        admin_account_id=account.id,
        action="admin.login",
        target_type="admin_account",
        target_id=str(account.id),
        detail={"username": account.username},
    )
    await session.flush()
    return AdminSessionResult(token=token, account=account)


async def get_account_by_session_token(session: AsyncSession, token: str | None) -> AdminAccount | None:
    if not token:
        return None
    now = _utcnow()
    result = await session.execute(
        select(AdminSession, AdminAccount)
        .join(AdminAccount, AdminAccount.id == AdminSession.admin_account_id)
        .where(AdminSession.token_hash == hash_token(token))
        .where(AdminSession.revoked_at.is_(None))
        .where(AdminSession.expires_at > now)
        .where(AdminAccount.status == "active")
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    admin_session, account = row
    admin_session.last_seen_at = now
    return account


async def logout_session(session: AsyncSession, token: str | None, account: AdminAccount | None) -> None:
    if not token:
        return
    result = await session.execute(
        select(AdminSession)
        .where(AdminSession.token_hash == hash_token(token))
        .where(AdminSession.revoked_at.is_(None))
        .limit(1)
    )
    admin_session = result.scalar_one_or_none()
    if admin_session is not None:
        admin_session.revoked_at = _utcnow()
    if account is not None:
        await append_audit(
            session,
            admin_account_id=account.id,
            action="admin.logout",
            target_type="admin_account",
            target_id=str(account.id),
            detail={},
        )


async def append_audit(
    session: AsyncSession,
    *,
    admin_account_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    session.add(
        AdminAuditLog(
            admin_account_id=admin_account_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
        )
    )
    await session.flush()


def serialize_admin(account: AdminAccount) -> dict:
    return {
        "id": account.id,
        "username": account.username,
        "display_name": account.display_name,
        "status": account.status,
        "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
    }
