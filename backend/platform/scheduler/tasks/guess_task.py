"""竞猜截止任务"""

from __future__ import annotations

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.activity.services.guess_service import close_due_events, format_event_runtime


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
            events = await close_due_events(session)
            for event in events:
                text = format_event_runtime(event) + "\n\n⏰ 已截止下注，等待管理员开奖。"
                if event.announcement_message_id:
                    try:
                        await app.bot.edit_message_text(
                            chat_id=event.chat_id,
                            message_id=event.announcement_message_id,
                            text=text,
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
                else:
                    msg = await app.bot.send_message(chat_id=event.chat_id, text=text, parse_mode="Markdown")
                    event.announcement_message_id = msg.message_id
            await session.commit()
