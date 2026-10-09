"""运营可审计事件写入。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.ops import OpsAuditEvent


async def record_ops_event(
    session: AsyncSession,
    *,
    domain: str,
    event_type: str,
    chat_id: int | None = None,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    severity: str = "info",
    detail: dict[str, Any] | None = None,
) -> OpsAuditEvent:
    event = OpsAuditEvent(
        domain=domain,
        event_type=event_type,
        chat_id=chat_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        severity=severity,
        detail=detail or {},
        created_at=dt.datetime.now(dt.UTC),
    )
    session.add(event)
    await session.flush()
    return event
