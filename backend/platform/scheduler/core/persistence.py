"""调度任务状态持久化：自动暂停可观测、可恢复。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.ops import SchedulerTaskState
from backend.platform.db.runtime.session import Database


async def load_task_states(session: AsyncSession) -> dict[str, SchedulerTaskState]:
    rows = (await session.execute(select(SchedulerTaskState))).scalars().all()
    return {row.task_name: row for row in rows}


async def upsert_task_state(
    session: AsyncSession,
    *,
    task_name: str,
    enabled: bool,
    auto_paused: bool = False,
    paused_reason: str | None = None,
    consecutive_errors: int = 0,
    total_runs: int = 0,
    total_errors: int = 0,
    last_success_at: dt.datetime | None = None,
    last_failure_at: dt.datetime | None = None,
    last_error: str | None = None,
) -> SchedulerTaskState:
    row = await session.get(SchedulerTaskState, task_name)
    if row is None:
        row = SchedulerTaskState(task_name=task_name)
        session.add(row)
    row.enabled = enabled
    row.auto_paused = auto_paused
    row.paused_reason = paused_reason
    row.consecutive_errors = consecutive_errors
    row.total_runs = total_runs
    row.total_errors = total_errors
    row.last_success_at = last_success_at
    row.last_failure_at = last_failure_at
    row.last_error = last_error
    row.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()
    return row


async def resume_task_state(session: AsyncSession, task_name: str) -> SchedulerTaskState | None:
    row = await session.get(SchedulerTaskState, task_name)
    if row is None:
        return None
    row.enabled = True
    row.auto_paused = False
    row.paused_reason = None
    row.consecutive_errors = 0
    row.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()
    return row


async def list_paused_tasks(session: AsyncSession) -> list[SchedulerTaskState]:
    stmt = select(SchedulerTaskState).where(
        (SchedulerTaskState.enabled.is_(False)) | (SchedulerTaskState.auto_paused.is_(True))
    )
    return list((await session.execute(stmt)).scalars().all())


async def persist_task_snapshot(db: Database, task) -> None:
    async with db.session_factory() as session:
        await upsert_task_state(
            session,
            task_name=task.name,
            enabled=task.enabled,
            auto_paused=bool(getattr(task, "auto_paused", False)),
            paused_reason=getattr(task, "paused_reason", None),
            consecutive_errors=task.error_count,
            total_runs=task.total_runs,
            total_errors=task.total_errors,
            last_success_at=task.last_success_at,
            last_failure_at=task.last_failure_at,
            last_error=task.last_error,
        )
        await session.commit()
