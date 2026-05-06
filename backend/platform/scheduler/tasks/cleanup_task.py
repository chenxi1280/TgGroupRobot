"""清理任务"""

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


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
        from backend.features.garage.services.garage_forward_service import GarageForwardService
        from backend.features.moderation.services.anti_flood_service import anti_flood_cleanup_job
        from backend.features.moderation.services.anti_spam_service import anti_spam_cleanup_job
        import structlog

        log = structlog.get_logger(__name__)
        await anti_flood_cleanup_job(app)
        await anti_spam_cleanup_job()
        db = app.bot_data.get("db") if app is not None else None
        if db is None:
            log.warning("cleanup_task_missing_db")
            return
        async with db.session_factory() as session:
            deleted = await GarageForwardService.purge_expired_audits(session)
            await session.commit()
        if deleted:
            log.info("cleanup_task_garage_forward_audits_purged", deleted_count=deleted)
