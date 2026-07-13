from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.verification.timeout_admin_service import (
    ACTION_CANCEL,
    ACTION_REPLAY,
    ACTION_RETRY,
    TimeoutOperation,
    TimeoutTaskFilter,
    apply_timeout_operation,
    list_timeout_tasks,
)
from backend.features.web_admin.auth_service import append_audit
from backend.features.web_admin.dependencies import admin_session, current_admin
from backend.platform.db.schema.models.core import AdminAccount
from backend.platform.delivery import DeliveryStatus


DEFAULT_STATUS_FILTER = (
    DeliveryStatus.retryable_failed,
    DeliveryStatus.permanent_failed,
    DeliveryStatus.uncertain,
)


class UncertainReplayRequest(BaseModel):
    confirm: Literal[True]


router = APIRouter()


@router.get("/admin/api/verification-timeouts")
async def list_verification_timeouts(
    *,
    chat_id: int,
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    _ = admin
    try:
        statuses = _parse_status_filter(status)
        items = await list_timeout_tasks(
            session,
            TimeoutTaskFilter(chat_id=chat_id, statuses=statuses, limit=limit),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok({"items": [_serialize_item(item) for item in items]})


@router.post("/admin/api/verification-timeouts/{challenge_id}/retry")
async def retry_verification_timeout(
    challenge_id: int,
    *,
    chat_id: int,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    return await _execute_operation(
        session,
        admin,
        challenge_id=challenge_id,
        chat_id=chat_id,
        action=ACTION_RETRY,
    )


@router.post("/admin/api/verification-timeouts/{challenge_id}/cancel")
async def cancel_verification_timeout(
    challenge_id: int,
    *,
    chat_id: int,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    return await _execute_operation(
        session,
        admin,
        challenge_id=challenge_id,
        chat_id=chat_id,
        action=ACTION_CANCEL,
    )


@router.post("/admin/api/verification-timeouts/{challenge_id}/replay")
async def replay_verification_timeout(
    challenge_id: int,
    *,
    chat_id: int,
    payload: UncertainReplayRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    _ = payload
    return await _execute_operation(
        session,
        admin,
        challenge_id=challenge_id,
        chat_id=chat_id,
        action=ACTION_REPLAY,
    )


async def _execute_operation(
    session: AsyncSession,
    admin: AdminAccount,
    *,
    challenge_id: int,
    chat_id: int,
    action: str,
):
    operation = TimeoutOperation(
        challenge_id=challenge_id,
        chat_id=chat_id,
        action=action,
        now=dt.datetime.now(dt.UTC),
    )
    try:
        await apply_timeout_operation(session, operation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await append_audit(
        session,
        admin_account_id=admin.id,
        action=f"verification_timeout.{action}",
        target_type="verification_challenge",
        target_id=str(challenge_id),
        detail={"chat_id": chat_id},
    )
    await session.commit()
    return _ok(message="操作已保存")


def _parse_status_filter(value: str | None) -> tuple[DeliveryStatus, ...]:
    if not value:
        return DEFAULT_STATUS_FILTER
    return tuple(DeliveryStatus(item.strip()) for item in value.split(",") if item.strip())


def _serialize_item(item) -> dict:
    return {
        "id": item.id,
        "chat_id": item.chat_id,
        "user_id": item.user_id,
        "status": item.status,
        "action": item.action,
        "attempts": item.attempts,
        "last_error": item.last_error,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _ok(data=None, message: str = "ok") -> dict:
    return {"success": True, "message": message, "data": data}
