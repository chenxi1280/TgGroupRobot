"""清理任务"""

from bot.services.automation.scheduler.core import ScheduledTask
from bot.services.automation.scheduler.task_config import TASK_CONFIG


class CleanupTask(ScheduledTask):
    """清理任务（反刷屏缓存清理）"""

    def __init__(self):
        config = TASK_CONFIG["cleanup"]
        super().__init__(
            name="cleanup",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行清理逻辑"""
        from bot.services.moderation.anti_flood_service import anti_flood_cleanup_job
        import structlog

        log = structlog.get_logger(__name__)
        await anti_flood_cleanup_job(app)
