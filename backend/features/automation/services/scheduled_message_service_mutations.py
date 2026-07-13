from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import TgChat
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask
from backend.shared.services.base import ValidationError
from backend.shared.time_helper import calculate_next_run_time

_RECALCULATE_KEYS = {"repeat_interval_min", "day_start_hour", "day_end_hour", "start_at"}


async def _new_short_id(session: AsyncSession) -> str:
    while True:
        short_id = secrets.token_hex(4)
        result = await session.execute(select(ScheduledMessageTask).where(ScheduledMessageTask.short_id == short_id))
        if result.scalar_one_or_none() is None:
            return short_id


def _apply_task_updates(task: ScheduledMessageTask, updates: dict[str, Any], nullable_fields: set[str]) -> None:
    for key, value in updates.items():
        if not hasattr(task, key):
            continue
        if value is None and key not in nullable_fields:
            continue
        setattr(task, key, value)


def _build_task(*, short_id: str, chat_id: int, creator_id: int, title: str, values: dict[str, Any]) -> ScheduledMessageTask:
    return ScheduledMessageTask(
        task_id=uuid.uuid4(), short_id=short_id, chat_id=chat_id,
        created_by_user_id=creator_id, title=title.strip(), enabled=values["enabled"],
        repeat_interval_min=values["repeat_interval_min"], day_start_hour=values["day_start_hour"],
        day_end_hour=values["day_end_hour"], start_at=values["start_at"], end_at=values["end_at"],
        text=values["text"], parse_mode=values["parse_mode"], media_type=values["media_type"],
        media_file_id=values["media_file_id"], buttons=values["buttons"],
        delete_previous=values["delete_previous"], pin_message=values["pin_message"],
    )


class ScheduledMessageMutationMixin:
    """定时消息服务的创建、更新与执行状态变更。"""

    @classmethod
    async def create_task(
        cls,
        session: AsyncSession,
        chat_id: int,
        created_by_user_id: int,
        *, title: str,
        **kwargs: Any,
    ) -> ScheduledMessageTask:
        chat = await session.get(TgChat, chat_id)
        if not chat:
            raise ValidationError(f"群组 {chat_id} 不存在")

        if not title or not title.strip():
            raise ValidationError("任务标题不能为空")

        repeat_interval_min = kwargs.get("repeat_interval_min", 60)
        cls.validate_repeat_interval(repeat_interval_min)

        day_start_hour = kwargs.get("day_start_hour", 0)
        day_end_hour = kwargs.get("day_end_hour", 23)
        cls.validate_day_period(day_start_hour, day_end_hour)

        start_at = kwargs.get("start_at")
        end_at = kwargs.get("end_at")
        cls.validate_future_end_at(end_at)
        cls.validate_time_range(start_at, end_at)

        media_type = kwargs.get("media_type", "none")
        media_file_id = kwargs.get("media_file_id")
        text = kwargs.get("text")
        enabled = kwargs.get("enabled", True)
        if enabled and not cls.has_sendable_payload(text=text, media_type=media_type, media_file_id=media_file_id):
            raise ValidationError("请先设置文本或封面")

        raw_buttons = kwargs.get("buttons", [])
        buttons = cls.normalize_buttons_config(raw_buttons) if raw_buttons else []

        values = {
            "enabled": enabled, "repeat_interval_min": repeat_interval_min,
            "day_start_hour": day_start_hour, "day_end_hour": day_end_hour,
            "start_at": start_at, "end_at": end_at, "text": text,
            "parse_mode": kwargs.get("parse_mode", "HTML"), "media_type": media_type,
            "media_file_id": media_file_id, "buttons": buttons,
            "delete_previous": kwargs.get("delete_previous", True),
            "pin_message": kwargs.get("pin_message", False),
        }
        task = _build_task(
            short_id=await _new_short_id(session), chat_id=chat_id,
            creator_id=created_by_user_id, title=title, values=values,
        )
        task.next_run_at = calculate_next_run_time(task)

        session.add(task)
        await session.flush()
        return task

    @classmethod
    async def update_task(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        **kwargs: Any,
    ) -> ScheduledMessageTask:
        task = await cls.get_task_by_id_or_404(session, task_id)

        _apply_task_updates(task, kwargs, cls._NULLABLE_UPDATE_FIELDS)

        if "day_start_hour" in kwargs or "day_end_hour" in kwargs:
            cls.validate_day_period(task.day_start_hour, task.day_end_hour)

        if "end_at" in kwargs:
            cls.validate_future_end_at(task.end_at)
        cls.validate_time_range(task.start_at, task.end_at)

        if task.enabled and not cls.has_sendable_content(task):
            task.enabled = False

        if _RECALCULATE_KEYS.intersection(kwargs):
            now_timestamp = int(dt.datetime.now(dt.UTC).timestamp())
            task.next_run_at = calculate_next_run_time(task, now_timestamp)

        await session.flush()
        return task

    @classmethod
    async def toggle_task_enabled(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        enabled: bool,
    ) -> ScheduledMessageTask:
        task = await cls.get_task_by_id_or_404(session, task_id)
        if enabled and not cls.has_sendable_content(task):
            raise ValidationError("请先设置文本或封面")
        task.enabled = enabled
        if enabled:
            now_timestamp = int(dt.datetime.now(dt.UTC).timestamp())
            task.next_run_at = calculate_next_run_time(task, now_timestamp)

        await session.flush()
        return task

    @classmethod
    async def delete_task(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
    ) -> bool:
        task = await cls.get_task_by_id_or_404(session, task_id)
        await session.delete(task)
        await session.flush()
        return True

    @classmethod
    async def mark_task_sent(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        message_id: int,
    ) -> ScheduledMessageTask:
        task = await cls.get_task_by_id_or_404(session, task_id)
        task.last_sent_message_id = message_id
        now_timestamp = int(dt.datetime.now(dt.UTC).timestamp())
        task.next_run_at = calculate_next_run_time(task, now_timestamp)
        await session.flush()
        return task

    @classmethod
    async def update_task_text(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        text: str | None,
    ) -> ScheduledMessageTask:
        return await cls.update_task(session, task_id, text=text)

    @classmethod
    async def update_task_media(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        media_type: str,
        *, media_file_id: str | None = None,
    ) -> ScheduledMessageTask:
        cls.validate_media_type(media_type)
        return await cls.update_task(
            session,
            task_id,
            media_type=media_type,
            media_file_id=media_file_id,
        )

    @classmethod
    async def update_task_buttons(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        buttons: list,
    ) -> ScheduledMessageTask:
        normalized_buttons = cls.normalize_buttons_config(buttons)
        return await cls.update_task(session, task_id, buttons=normalized_buttons)

    @classmethod
    async def update_task_repeat(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        repeat_interval_min: int,
    ) -> ScheduledMessageTask:
        cls.validate_repeat_interval(repeat_interval_min)
        return await cls.update_task(session, task_id, repeat_interval_min=repeat_interval_min)

    @classmethod
    async def update_task_day_period(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        day_start_hour: int,
        *, day_end_hour: int,
    ) -> ScheduledMessageTask:
        cls.validate_day_period(day_start_hour, day_end_hour)
        return await cls.update_task(
            session,
            task_id,
            day_start_hour=day_start_hour,
            day_end_hour=day_end_hour,
        )

    @classmethod
    async def update_task_start_at(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        date_time_str: str | None,
    ) -> ScheduledMessageTask:
        start_at = cls.parse_optional_datetime(date_time_str)
        return await cls.update_task(session, task_id, start_at=start_at)

    @classmethod
    async def update_task_end_at(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        date_time_str: str | None,
    ) -> ScheduledMessageTask:
        end_at = cls.parse_optional_datetime(date_time_str)
        return await cls.update_task(session, task_id, end_at=end_at)

    @classmethod
    async def update_task_toggle_option(
        cls,
        session: AsyncSession,
        task_id: str | uuid.UUID,
        option: str,
        *, value: bool,
    ) -> ScheduledMessageTask:
        cls.validate_toggle_option(option)
        return await cls.update_task(session, task_id, **{option: value})
