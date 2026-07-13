from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.automation.ad_delivery_admin_service import (
    cancel_delivery,
    list_delivery_history,
    replay_uncertain_delivery,
    retry_delivery,
)
from backend.features.web_admin.auth_service import append_audit
from backend.features.web_admin.dependencies import admin_session, current_admin
from backend.platform.db.schema.models.core import AdminAccount
from backend.platform.delivery import DeliveryStatus
from backend.shared.services.base import ServiceError

router = APIRouter()


class AdReplayRequest(BaseModel):
    confirm: Literal[True]
    reason: str = Field(min_length=1, max_length=500)


@router.get("/admin/api/ad-deliveries")
async def list_ad_deliveries(
    *,
    chat_id: int,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    _ = admin
    try:
        parsed_status = DeliveryStatus(status).value if status else None
        items = await list_delivery_history(session, chat_id, status=parsed_status, limit=limit)
    except (ValueError, ServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok({"items": [_serialize(item) for item in items]})


@router.post("/admin/api/ad-deliveries/{history_id}/retry")
async def retry_ad_delivery(
    history_id: int,
    *,
    chat_id: int,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    await _apply_simple(session, admin, history_id=history_id, chat_id=chat_id, action="retry")
    return _ok(message="重试已保存")


@router.post("/admin/api/ad-deliveries/{history_id}/cancel")
async def cancel_ad_delivery(
    history_id: int,
    *,
    chat_id: int,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    await _apply_simple(session, admin, history_id=history_id, chat_id=chat_id, action="cancel")
    return _ok(message="取消已保存")


@router.post("/admin/api/ad-deliveries/{history_id}/replay")
async def replay_ad_delivery(
    history_id: int,
    *,
    chat_id: int,
    payload: AdReplayRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    _ = payload.confirm
    try:
        replay_id = await replay_uncertain_delivery(
            session,
            history_id,
            chat_id,
            admin_id=admin.id,
            reason=payload.reason,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _audit(
        session,
        admin,
        history_id=history_id,
        chat_id=chat_id,
        action="replay",
        detail={"reason": payload.reason, "replay_id": replay_id},
    )
    await session.commit()
    return _ok({"replay_id": replay_id}, message="重放已保存")


async def _apply_simple(session, admin, *, history_id: int, chat_id: int, action: str) -> None:
    try:
        if action == "retry":
            await retry_delivery(session, history_id, chat_id)
        else:
            await cancel_delivery(session, history_id, chat_id)
    except ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _audit(session, admin, history_id=history_id, chat_id=chat_id, action=action, detail={})
    await session.commit()


async def _audit(
    session,
    admin,
    *,
    history_id: int,
    chat_id: int,
    action: str,
    detail: dict,
) -> None:
    await append_audit(
        session,
        admin_account_id=admin.id,
        action=f"ad_delivery.{action}",
        target_type="ad_rotation_history",
        target_id=str(history_id),
        detail={"chat_id": chat_id, **detail},
    )


def _serialize(item) -> dict:
    return {
        "id": item.id,
        "chat_id": item.chat_id,
        "campaign_id": item.campaign_id,
        "title": item.title_snapshot,
        "status": item.status,
        "attempts": item.attempt_count,
        "error": item.error_code or item.error_message,
        "scheduled_for": item.scheduled_for.isoformat() if item.scheduled_for else None,
        "next_retry_at": item.next_retry_at.isoformat() if item.next_retry_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _ok(data=None, message: str = "ok") -> dict:
    return {"success": True, "message": message, "data": data}
