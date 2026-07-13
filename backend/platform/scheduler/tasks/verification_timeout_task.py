"""Durable verification-timeout scheduler task."""
from __future__ import annotations

import datetime as dt

import structlog
from telegram.ext import Application

from backend.features.verification.timeout_executor import (
    TelegramVerificationTimeoutExecutor,
)
from backend.features.verification.timeout_repository import (
    SqlAlchemyVerificationTimeoutStore,
)
from backend.features.verification.timeout_worker import (
    VerificationTimeoutWorker,
    WorkerDependencies,
)
from backend.platform.db.runtime.session import Database
from backend.platform.scheduler.core.core import ScheduledTask
from backend.shared.services.chat_service import get_chat_settings


TASK_INTERVAL_SECONDS = 60
MAX_CONSECUTIVE_FAILURES = 3

log = structlog.get_logger(__name__)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _build_timeout_worker(app: Application) -> VerificationTimeoutWorker:
    db: Database = app.bot_data["db"]
    store = SqlAlchemyVerificationTimeoutStore(db, get_chat_settings)
    executor = TelegramVerificationTimeoutExecutor(app.bot)
    return VerificationTimeoutWorker(
        WorkerDependencies(
            store=store,
            executor=executor,
            clock=_utc_now,
        )
    )


async def check_verification_timeouts(app: Application) -> None:
    summary = await _build_timeout_worker(app).run()
    log.info(
        "verification_timeouts_processed",
        claimed=summary.claimed,
        succeeded=summary.succeeded,
        failed=summary.failed,
        recovered=summary.recovered,
    )


class VerificationTimeoutTask(ScheduledTask):
    def __init__(self) -> None:
        super().__init__(
            name="verification_timeout",
            interval=TASK_INTERVAL_SECONDS,
            enabled=True,
            max_consecutive_failures=MAX_CONSECUTIVE_FAILURES,
        )

    async def execute(self, app: Application) -> None:
        await check_verification_timeouts(app)
