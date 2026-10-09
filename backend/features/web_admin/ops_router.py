"""跨域失败任务运营台 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.api_common import ok
from backend.features.web_admin.auth_service import append_audit
from backend.features.web_admin.dependencies import admin_session, current_admin
from backend.features.web_admin.ops_service import get_ops_summary, list_failed_items
from backend.platform.db.schema.models.core import AdminAccount
from backend.platform.scheduler.core.persistence import resume_task_state

router = APIRouter()


@router.get("/admin/api/ops/summary")
async def ops_summary(
    *,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    _ = admin
    return ok(await get_ops_summary(session))


@router.get("/admin/api/ops/failures")
async def ops_failures(
    *,
    domain: str = Query(..., description="verification_timeout|verification_prompt|garage_forward|scheduled_message|ad_rotation"),
    limit: int = Query(default=50, ge=1, le=100),
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    _ = admin
    try:
        items = await list_failed_items(session, domain=domain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({"domain": domain, "items": items})


@router.post("/admin/api/ops/scheduler/{task_name}/resume")
async def resume_scheduler_task(
    task_name: str,
    request: Request,
    *,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(admin_session),
):
    row = await resume_task_state(session, task_name)
    if row is None:
        raise HTTPException(status_code=404, detail="task state not found")

    scheduler = getattr(request.app.state, "scheduler", None)
    resumed_live = False
    if scheduler is not None and hasattr(scheduler, "resume_task"):
        resumed_live = bool(scheduler.resume_task(task_name))

    await append_audit(
        session,
        admin_account_id=admin.id,
        action="scheduler.resume",
        target_type="scheduler_task",
        target_id=task_name,
        detail={"resumed_live": resumed_live},
    )
    await session.commit()
    return ok(
        {
            "task_name": task_name,
            "enabled": row.enabled,
            "auto_paused": row.auto_paused,
            "resumed_live": resumed_live,
        },
        "任务已恢复",
    )
