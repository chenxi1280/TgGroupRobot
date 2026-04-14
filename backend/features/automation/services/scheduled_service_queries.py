from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ScheduledMessage
from backend.shared.services.base import ServiceBase


async def get_scheduled_message(session: AsyncSession, message_id: int) -> ScheduledMessage | None:
    return await ServiceBase._get_by_id(session, ScheduledMessage, message_id)


async def get_chat_scheduled_messages(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[ScheduledMessage]:
    return await ServiceBase._get_list(
        session,
        ScheduledMessage,
        filters={"chat_id": chat_id},
        active_only=active_only,
        order_by="created_at",
        descending=True,
    )


async def get_pending_messages(
    session: AsyncSession,
    current_time: dt.datetime,
) -> list[ScheduledMessage]:
    messages = await ServiceBase._get_list(
        session,
        ScheduledMessage,
        active_only=True,
        order_by="next_send_time",
        descending=False,
    )
    return [message for message in messages if message.next_send_time <= current_time]
