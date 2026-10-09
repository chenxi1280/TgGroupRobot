"""跨域失败任务聚合查询。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.alliance import GarageForwardRetryQueue
from backend.platform.db.schema.models.automation import AdRotationHistory
from backend.platform.db.schema.models.moderation import VerificationChallenge
from backend.platform.db.schema.models.ops import OpsAuditEvent, SchedulerTaskState
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog
from backend.platform.delivery import DeliveryStatus

_FAILURE_STATUSES = (
    DeliveryStatus.retryable_failed.value,
    DeliveryStatus.permanent_failed.value,
    DeliveryStatus.uncertain.value,
)

_DOMAIN_SPECS = {
    "verification_timeout": (VerificationChallenge, "timeout_status", ("timeout_status", "timeout_last_error", "timeout_attempts", True)),
    "verification_prompt": (VerificationChallenge, "prompt_status", ("prompt_status", "prompt_last_error", "prompt_attempts", True)),
    "garage_forward": (GarageForwardRetryQueue, "status", ("status", "last_error", "retry_count", False)),
    "scheduled_message": (ScheduledMessageLog, "status", ("status", "error_message", "attempt_count", False)),
    "ad_rotation": (AdRotationHistory, "status", ("status", "error_message", "attempt_count", False)),
}


async def _count_by_status(
    session: AsyncSession,
    *,
    status_col,
    statuses: tuple[str, ...],
) -> dict[str, int]:
    stmt = (
        select(status_col, func.count())
        .where(status_col.in_(statuses))
        .group_by(status_col)
    )
    rows = (await session.execute(stmt)).all()
    return {str(status): int(count) for status, count in rows}


async def _domain_failure_counts(session: AsyncSession) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for domain, (model, status_attr, _) in _DOMAIN_SPECS.items():
        result[domain] = await _count_by_status(
            session, status_col=getattr(model, status_attr), statuses=_FAILURE_STATUSES
        )
    return result


def _serialize_paused_task(row: SchedulerTaskState) -> dict:
    return {
        "task_name": row.task_name,
        "enabled": row.enabled,
        "auto_paused": row.auto_paused,
        "paused_reason": row.paused_reason,
        "consecutive_errors": row.consecutive_errors,
        "last_error": row.last_error,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_ops_event(event: OpsAuditEvent) -> dict:
    return {
        "id": event.id,
        "domain": event.domain,
        "event_type": event.event_type,
        "chat_id": event.chat_id,
        "user_id": event.user_id,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "severity": event.severity,
        "detail": event.detail,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def get_ops_summary(session: AsyncSession) -> dict:
    paused_tasks = list(
        (
            await session.execute(
                select(SchedulerTaskState).where(
                    (SchedulerTaskState.enabled.is_(False)) | (SchedulerTaskState.auto_paused.is_(True))
                )
            )
        ).scalars().all()
    )
    recent_events = list(
        (
            await session.execute(
                select(OpsAuditEvent).order_by(OpsAuditEvent.created_at.desc()).limit(20)
            )
        ).scalars().all()
    )
    return {
        "domains": await _domain_failure_counts(session),
        "paused_scheduler_tasks": [_serialize_paused_task(row) for row in paused_tasks],
        "recent_ops_events": [_serialize_ops_event(event) for event in recent_events],
    }


def _map_failure_row(domain: str, row, *, fields) -> dict:
    status_attr, error_attr, attempts_attr, with_user = fields
    payload = {
        "domain": domain,
        "id": row.id,
        "chat_id": row.chat_id,
        "status": getattr(row, status_attr),
        "error": getattr(row, error_attr),
        "attempts": getattr(row, attempts_attr),
    }
    if with_user:
        payload["user_id"] = row.user_id
    return payload


async def list_failed_items(session: AsyncSession, *, domain: str, limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 100))
    spec = _DOMAIN_SPECS.get(domain)
    if spec is None:
        raise ValueError(f"unsupported domain: {domain}")
    model, status_attr, fields = spec
    status_col = getattr(model, status_attr)
    rows = (
        await session.execute(
            select(model)
            .where(status_col.in_(_FAILURE_STATUSES))
            .order_by(model.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_map_failure_row(domain, row, fields=fields) for row in rows]
