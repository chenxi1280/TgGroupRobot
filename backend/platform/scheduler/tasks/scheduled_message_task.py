from __future__ import annotations

import datetime as dt

import structlog

from backend.features.automation.scheduled_delivery_executor import TelegramScheduledDeliveryExecutor
from backend.features.automation.scheduled_delivery_worker import (
    ScheduledDeliveryWorker,
    ScheduledWorkerDependencies,
)
from backend.features.automation.scheduled_occurrence_repository import SqlAlchemyScheduledOccurrenceStore
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG

log = structlog.get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_MAX_FAILURES = 3


class ScheduledMessageTaskRunner(ScheduledTask):
    """可靠定时消息 occurrence 调度入口。"""

    def __init__(self) -> None:
        config = TASK_CONFIG.get("scheduled_message", {})
        super().__init__(
            name="scheduled_message",
            interval=config.get("interval", DEFAULT_INTERVAL_SECONDS),
            enabled=config.get("enabled", True),
            max_consecutive_failures=config.get("max_consecutive_failures", DEFAULT_MAX_FAILURES),
        )

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        dependencies = ScheduledWorkerDependencies(
            store=SqlAlchemyScheduledOccurrenceStore(db),
            executor=TelegramScheduledDeliveryExecutor(app),
            clock=lambda: dt.datetime.now(dt.UTC),
        )
        summary = await ScheduledDeliveryWorker(dependencies).run()
        if summary.created or summary.claimed or summary.recovered:
            log.info(
                "scheduled_message_tick_finished",
                created=summary.created,
                claimed=summary.claimed,
                succeeded=summary.succeeded,
                failed=summary.failed,
                recovered=summary.recovered,
            )
