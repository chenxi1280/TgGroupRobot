from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.guess_service_parsing import now
from backend.platform.db.schema.models.expansion import GuessEvent, GuessSetting
from backend.shared.services.module_settings_service import ModuleSettingsService


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> GuessSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(GuessSetting, chat_id)
    if setting is None:
        setting = GuessSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> GuessSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = now()
    await session.flush()
    return setting


async def count_events_by_status(session: AsyncSession, chat_id: int) -> dict[str, int]:
    result = await session.execute(
        select(GuessEvent.status, func.count(GuessEvent.id)).where(GuessEvent.chat_id == chat_id).group_by(GuessEvent.status)
    )
    counts = {"pending": 0, "running": 0, "opened": 0, "cancelled": 0}
    for status, total in result.all():
        counts[str(status)] = int(total)
    return counts


async def list_events(session: AsyncSession, chat_id: int, status: str, *, limit: int = 10) -> list[GuessEvent]:
    stmt = select(GuessEvent).where(GuessEvent.chat_id == chat_id, GuessEvent.status == status).order_by(desc(GuessEvent.id)).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_event(session: AsyncSession, chat_id: int, event_id: int) -> GuessEvent | None:
    result = await session.execute(select(GuessEvent).where(GuessEvent.chat_id == chat_id, GuessEvent.id == event_id))
    return result.scalar_one_or_none()


async def get_running_event_by_keyword(session: AsyncSession, chat_id: int, keyword: str) -> GuessEvent | None:
    stmt = (
        select(GuessEvent)
        .where(GuessEvent.chat_id == chat_id, GuessEvent.command_keyword == keyword, GuessEvent.status.in_(["running", "pending"]))
        .order_by(desc(GuessEvent.id))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def close_due_events(session: AsyncSession) -> list[GuessEvent]:
    event_ids = await list_due_event_ids(session)
    events: list[GuessEvent] = []
    for event_id in event_ids:
        event = await close_due_event(session, event_id)
        if event is not None:
            events.append(event)
    await session.flush()
    return events


async def list_due_event_ids(session: AsyncSession) -> list[int]:
    stmt = select(GuessEvent.id).where(GuessEvent.status == "running", GuessEvent.deadline_at <= now())
    result = await session.execute(stmt)
    return [int(event_id) for event_id in result.scalars().all()]


async def close_due_event(session: AsyncSession, event_id: int) -> GuessEvent | None:
    stmt = (
        select(GuessEvent)
        .where(GuessEvent.id == event_id, GuessEvent.status == "running", GuessEvent.deadline_at <= now())
        .with_for_update()
    )
    result = await session.execute(stmt)
    event = result.scalar_one_or_none()
    if event is None:
        return None
    event.status = "pending"
    event.updated_at = now()
    await session.flush()
    return event
