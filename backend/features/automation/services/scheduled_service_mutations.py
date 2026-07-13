from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.automation.services.scheduled_service_queries import get_scheduled_message
from backend.platform.db.schema.models.core import ScheduledMessage
from backend.platform.db.schema.models.enums import ScheduleType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CreateResult, ToggleResult, UpdateResult


def calculate_next_send_time(
    schedule_type: str,
    interval_minutes: int | None = None,
    base_time: dt.datetime | None = None,
) -> dt.datetime:
    if base_time is None:
        base_time = dt.datetime.now(dt.UTC)

    match schedule_type:
        case ScheduleType.none.value:
            return base_time
        case ScheduleType.every_minute.value:
            return base_time + dt.timedelta(minutes=1)
        case ScheduleType.every_5_minutes.value:
            return base_time + dt.timedelta(minutes=5)
        case ScheduleType.every_15_minutes.value:
            return base_time + dt.timedelta(minutes=15)
        case ScheduleType.every_30_minutes.value:
            return base_time + dt.timedelta(minutes=30)
        case ScheduleType.every_hour.value:
            return base_time + dt.timedelta(hours=1)
        case ScheduleType.every_6_hours.value:
            return base_time + dt.timedelta(hours=6)
        case ScheduleType.every_12_hours.value:
            return base_time + dt.timedelta(hours=12)
        case ScheduleType.every_day.value:
            return base_time + dt.timedelta(days=1)
        case ScheduleType.custom.value:
            if interval_minutes and interval_minutes > 0:
                return base_time + dt.timedelta(minutes=interval_minutes)
            return base_time
        case _:
            return base_time


async def create_scheduled_message(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    *, content: str,
    schedule_type: str,
    interval_minutes: int | None = None,
    initial_delay_minutes: int = 0,
    repeat_enabled: bool = False,
) -> CreateResult:
    if not content or not content.strip():
        return CreateResult(success=False, reason="invalid_content")

    valid_types = [item.value for item in ScheduleType]
    if schedule_type not in valid_types:
        return CreateResult(success=False, reason="invalid_schedule_type")

    if schedule_type == ScheduleType.custom.value and (not interval_minutes or interval_minutes <= 0):
        return CreateResult(success=False, reason="invalid_interval")

    base_time = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=initial_delay_minutes)
    next_send_time = calculate_next_send_time(schedule_type, interval_minutes, base_time)
    message = ScheduledMessage(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        content=content,
        schedule_type=schedule_type,
        interval_minutes=interval_minutes,
        is_active=True,
        next_send_time=next_send_time,
        repeat_enabled=repeat_enabled,
    )
    session.add(message)
    await session.flush()
    return CreateResult(success=True, reason="ok", entity=message, entity_id=message.id)


async def update_scheduled_message(
    session: AsyncSession,
    message_id: int,
    content: str | None = None,
    *, schedule_type: str | None = None,
    interval_minutes: int | None = None,
) -> UpdateResult:
    message = await get_scheduled_message(session, message_id)
    if not message:
        return UpdateResult(success=False, reason="not_found")

    updates: dict[str, object] = {}
    if content is not None:
        if not content or not content.strip():
            return UpdateResult(success=False, reason="invalid_content")
        updates["content"] = content

    if schedule_type is not None:
        valid_types = [item.value for item in ScheduleType]
        if schedule_type not in valid_types:
            return UpdateResult(success=False, reason="invalid_schedule_type")
        updates["schedule_type"] = schedule_type

    if interval_minutes is not None:
        updates["interval_minutes"] = interval_minutes

    await ServiceBase._update_entity(session, message, updates)
    message.next_send_time = calculate_next_send_time(
        message.schedule_type,
        message.interval_minutes,
        dt.datetime.now(dt.UTC),
    )
    return UpdateResult(success=True, reason="ok", entity=message)


async def toggle_scheduled_message(session: AsyncSession, message_id: int) -> ToggleResult:
    message = await get_scheduled_message(session, message_id)
    if not message:
        return ToggleResult(success=False, reason="not_found")
    await ServiceBase._update_entity(session, message, {"is_active": not message.is_active})
    return ToggleResult(success=True, reason="ok", entity=message)


async def delete_scheduled_message(session: AsyncSession, message_id: int) -> bool:
    message = await get_scheduled_message(session, message_id)
    if not message:
        return False
    await ServiceBase._delete_entity(session, message)
    return True


async def mark_message_sent(session: AsyncSession, message: ScheduledMessage) -> None:
    updates: dict[str, object] = {
        "last_sent_at": dt.datetime.now(dt.UTC),
        "send_count": message.send_count + 1,
    }
    if not message.repeat_enabled:
        updates["is_active"] = False
    elif message.schedule_type != ScheduleType.none.value:
        updates["next_send_time"] = calculate_next_send_time(
            message.schedule_type,
            message.interval_minutes,
            dt.datetime.now(dt.UTC),
        )
    else:
        updates["is_active"] = False
    await ServiceBase._update_entity(session, message, updates)
