from __future__ import annotations

import datetime as dt

from backend.features.garage.forward_delivery_executor import TelegramGarageForwardExecutor
from backend.features.garage.forward_delivery_repository import SqlAlchemyGarageForwardStore
from backend.features.garage.forward_delivery_worker import (
    GarageForwardWorker,
    GarageWorkerDependencies,
)
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


class GarageForwardRetryTask(ScheduledTask):
    def __init__(self) -> None:
        config = TASK_CONFIG["garage_forward_retry"]
        super().__init__(
            name="garage_forward_retry",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        db = app.bot_data.get("db") if app is not None else None
        if db is None:
            raise RuntimeError("garage forward database is unavailable")
        dependencies = GarageWorkerDependencies(
            store=SqlAlchemyGarageForwardStore(db),
            executor=TelegramGarageForwardExecutor(app.bot),
            clock=lambda: dt.datetime.now(dt.UTC),
        )
        await GarageForwardWorker(dependencies).run()
