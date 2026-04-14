"""广告发送任务"""

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


class AdsTask(ScheduledTask):
    """广告发送任务"""

    def __init__(self):
        config = TASK_CONFIG["ads"]
        super().__init__(
            name="ads",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行广告发送逻辑"""
        from backend.features.automation.services.ad_rotation_service import dispatch_due_rotation_rules
        import structlog

        log = structlog.get_logger(__name__)
        dispatched = await dispatch_due_rotation_rules(app)
        log.info("ad_rotation_tick_finished", dispatched=dispatched)
