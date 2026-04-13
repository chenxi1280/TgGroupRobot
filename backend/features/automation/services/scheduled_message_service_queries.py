from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask
from backend.shared.services.base import NotFoundError


class ScheduledMessageQueryMixin:
    """定时消息服务的查询职责。"""

    @staticmethod
    async def get_task_by_id(
        session: AsyncSession,
        task_id: str | uuid.UUID,
    ) -> ScheduledMessageTask | None:
        task_key = str(task_id)

        stmt = select(ScheduledMessageTask).where(ScheduledMessageTask.short_id == task_key)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()

        if not task:
            try:
                task_uuid = task_id if isinstance(task_id, uuid.UUID) else uuid.UUID(task_key)
            except (TypeError, ValueError, AttributeError):
                return None

            stmt = select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_uuid)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()

        return task

    @classmethod
    async def get_task_by_id_or_404(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
    ) -> ScheduledMessageTask:
        task = await cls.get_task_by_id(session, task_id)
        if not task:
            raise NotFoundError(f"任务 {task_id} 不存在")
        return task

    @classmethod
    async def get_task_in_chat_or_404(
        cls,
        session: AsyncSession,
        chat_id: int,
        task_id: str | uuid.UUID,
    ) -> ScheduledMessageTask:
        task = await cls.get_task_by_id_or_404(session, task_id)
        if task.chat_id != chat_id:
            raise NotFoundError(f"群组 {chat_id} 下不存在任务 {task_id}")
        return task

    @staticmethod
    async def list_tasks(
        session: AsyncSession,
        chat_id: int,
        enabled_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScheduledMessageTask]:
        stmt = select(ScheduledMessageTask).where(ScheduledMessageTask.chat_id == chat_id)
        if enabled_only:
            stmt = stmt.where(ScheduledMessageTask.enabled == True)

        stmt = stmt.order_by(ScheduledMessageTask.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_due_tasks(
        session: AsyncSession,
        limit: int = 100,
    ) -> list[ScheduledMessageTask]:
        now = int(dt.datetime.now(dt.UTC).timestamp())
        stmt = (
            select(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.enabled == True,
                ScheduledMessageTask.next_run_at <= now,
            )
            .order_by(ScheduledMessageTask.next_run_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
