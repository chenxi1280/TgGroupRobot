from __future__ import annotations

import asyncio
import sys

from telegram import Update

from backend.app.bootstrap import (
    _PID_FILE,
    _check_single_instance,
    _should_skip_single_instance_lock,
    _validate_schema_or_exit,
    build_application,
    log,
)
from backend.platform.scheduler.core import Scheduler
from backend.platform.scheduler.tasks import (
    AdsTask,
    AuctionTask,
    BottomButtonTask,
    CleanupTask,
    EngagementTask,
    GameTask,
    GroupLockTask,
    GuessTask,
    LotteryTask,
    ScheduledMessageTaskRunner,
    SolitaireTask,
    TeacherSearchTask,
    VerificationTimeoutTask,
)


async def run_bot_with_scheduler() -> None:
    app = build_application()
    log.info("bot_starting")

    scheduler = Scheduler(app)
    scheduler.register_tasks([
        LotteryTask(),
        AuctionTask(),
        SolitaireTask(),
        AdsTask(),
        CleanupTask(),
        VerificationTimeoutTask(),
        ScheduledMessageTaskRunner(),
        GroupLockTask(),
        BottomButtonTask(),
        EngagementTask(),
        GameTask(),
        GuessTask(),
        TeacherSearchTask(),
    ])

    await _validate_schema_or_exit(app)
    await scheduler.start()
    initialized = False
    started = False
    polling_started = False

    try:
        await app.initialize()
        initialized = True
        await app.start()
        started = True
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        polling_started = True
        log.info("polling_started", allowed_updates="ALL_TYPES")
        await asyncio.Event().wait()
    finally:
        await scheduler.stop()
        if polling_started and app.updater is not None:
            await app.updater.stop()
        if started:
            await app.stop()
        if initialized:
            await app.shutdown()


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    _check_single_instance()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_bot_with_scheduler())
        finally:
            loop.close()
    except KeyboardInterrupt:
        log.info("bot_shutting_down")


def main_polling() -> None:
    app = build_application()
    log.info("bot_starting")
    asyncio.run(_validate_schema_or_exit(app))
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
