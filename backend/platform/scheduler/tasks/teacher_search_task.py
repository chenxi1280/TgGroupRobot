"""老师搜索周期维护任务。"""

from __future__ import annotations

import structlog

from backend.features.garage.services.garage_features_service import TeacherSearchService
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG

log = structlog.get_logger(__name__)


class TeacherSearchTask(ScheduledTask):
    def __init__(self) -> None:
        config = TASK_CONFIG["teacher_search"]
        super().__init__(
            name="teacher_search",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        async with db.session_factory() as session:
            reset_count = await TeacherSearchService.reset_stale_open_course_flags(session)
            await session.commit()
        if reset_count:
            log.info("teacher_search_open_course_flags_reset", reset_count=reset_count)
