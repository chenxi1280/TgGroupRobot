"""底部按钮周期刷新任务"""

from __future__ import annotations

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.group_ops.services.bottom_button_service import generate_buttons, list_due_repeat_generate


class BottomButtonTask(ScheduledTask):
    def __init__(self) -> None:
        config = TASK_CONFIG["bottom_button"]
        super().__init__(
            name="bottom_button",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        async with db.session_factory() as session:
            due_settings = await list_due_repeat_generate(session)
            for setting in due_settings:
                await generate_buttons(app, session, setting.chat_id)
            await session.commit()
