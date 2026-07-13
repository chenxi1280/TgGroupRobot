"""竞猜截止任务"""

from __future__ import annotations

import structlog
from types import SimpleNamespace

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.activity.services.guess_service import close_due_event, format_event_runtime, list_due_event_ids
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)


async def _publish_closed_event(context, event, *, event_id: int, text: str) -> bool:
    if not event.announcement_message_id:
        msg = await PublishService.send(context, chat_id=event.chat_id, text=text, parse_mode="Markdown")
        event.announcement_message_id = msg.message_id
        return True
    try:
        await PublishService.edit(
            context,
            chat_id=event.chat_id,
            message_id=event.announcement_message_id,
            text=text,
            parse_mode="Markdown",
        )
        return True
    except Exception as exc:
        log.warning(
            "guess_deadline_notice_edit_failed",
            event_id=event_id,
            chat_id=event.chat_id,
            message_id=event.announcement_message_id,
            error=str(exc),
        )
    msg = await PublishService.send(context, chat_id=event.chat_id, text=text, parse_mode="Markdown")
    event.announcement_message_id = msg.message_id
    return True


async def _close_and_publish(db, app, event_id: int) -> None:
    async with db.session_factory() as session:
        event = await close_due_event(session, event_id)
        if event is None:
            await session.commit()
            return
        context = SimpleNamespace(bot=app.bot, application=app)
        try:
            await _publish_closed_event(
                context,
                event,
                event_id=event_id,
                text=format_event_runtime(event),
            )
        except Exception as exc:
            await session.rollback()
            log.error("guess_deadline_notice_failed", event_id=event_id, error=str(exc))
            return
        await session.commit()


class GuessTask(ScheduledTask):
    def __init__(self) -> None:
        config = TASK_CONFIG["guess"]
        super().__init__(
            name="guess",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        async with db.session_factory() as session:
            event_ids = await list_due_event_ids(session)
            await session.commit()
        for event_id in event_ids:
            await _close_and_publish(db, app, event_id)
