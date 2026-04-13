"""定时消息发送任务"""

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


class MessageTask(ScheduledTask):
    """定时消息发送任务"""

    def __init__(self):
        config = TASK_CONFIG["message"]
        super().__init__(
            name="message",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行定时消息发送逻辑"""
        from backend.features.automation.services.scheduled_service import (
            get_pending_messages,
            mark_message_sent,
        )
        import datetime as dt
        import structlog

        log = structlog.get_logger(__name__)
        db = app.bot_data["db"]

        current_time = dt.datetime.now(dt.UTC)
        async with db.session_factory() as session:
            messages = await get_pending_messages(session, current_time)
            for msg in messages:
                try:
                    await app.bot.send_message(chat_id=msg.chat_id, text=msg.content)
                    await mark_message_sent(session, msg)
                    log.info(
                        "scheduled_message_sent",
                        message_id=msg.id,
                        chat_id=msg.chat_id,
                        schedule_type=msg.schedule_type,
                    )
                except Exception as e:
                    log.error(
                        "scheduled_message_send_failed",
                        message_id=msg.id,
                        chat_id=msg.chat_id,
                        error=str(e),
                    )
            await session.commit()
