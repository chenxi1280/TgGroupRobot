from __future__ import annotations

import asyncio
import signal
import sys
import time

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


def _register_scheduler_tasks(scheduler: Scheduler) -> None:
    from backend.platform.scheduler.tasks import (
        AdsTask,
        AuctionTask,
        BottomButtonTask,
        CleanupTask,
        EngagementTask,
        GameTask,
        GarageForwardRetryTask,
        GroupLockTask,
        GuessTask,
        LotteryTask,
        RenameMonitorTask,
        ScheduledMessageTaskRunner,
        SolitaireTask,
        TeacherSearchTask,
        VerificationTimeoutTask,
    )

    scheduler.register_tasks([
        LotteryTask(),
        AuctionTask(),
        SolitaireTask(),
        AdsTask(),
        CleanupTask(),
        VerificationTimeoutTask(),
        ScheduledMessageTaskRunner(),
        GroupLockTask(),
        RenameMonitorTask(),
        BottomButtonTask(),
        EngagementTask(),
        GameTask(),
        GuessTask(),
        TeacherSearchTask(),
        GarageForwardRetryTask(),
    ])


async def _wait_for_shutdown_signal() -> None:
    """Wait until the process receives a shutdown signal."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled_signals: list[signal.Signals] = []

    def _request_shutdown(received_signal: signal.Signals) -> None:
        log.info("shutdown_signal_received", signal=received_signal.name)
        stop_event.set()

    if sys.platform != "win32":
        for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(shutdown_signal, _request_shutdown, shutdown_signal)
                handled_signals.append(shutdown_signal)
            except (NotImplementedError, RuntimeError, ValueError):
                log.warning("shutdown_signal_handler_unavailable", signal=shutdown_signal.name)

    try:
        await stop_event.wait()
    finally:
        for shutdown_signal in handled_signals:
            loop.remove_signal_handler(shutdown_signal)


async def run_bot_with_scheduler() -> None:
    startup_started = time.perf_counter()
    app = build_application()
    log.info("bot_starting")

    settings = app.bot_data["settings"]
    scheduler = Scheduler(
        app,
        run_immediately=getattr(settings, "scheduler_run_immediately", False),
        initial_stagger_seconds=getattr(settings, "scheduler_initial_stagger_seconds", 0.0),
    )
    await _validate_schema_or_exit(app)
    initialized = False
    started = False
    polling_started = False
    scheduler_started = False
    admin_web_server = None
    admin_web_task: asyncio.Task | None = None

    try:
        await app.initialize()
        initialized = True
        await app.start()
        started = True
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        polling_started = True
        log.info(
            "polling_started",
            allowed_updates="ALL_TYPES",
            startup_seconds=round(time.perf_counter() - startup_started, 3),
        )
        _register_scheduler_tasks(scheduler)
        await scheduler.start()
        scheduler_started = True
        if getattr(settings, "admin_web_enabled", True):
            from backend.features.web_admin.app import create_admin_web_app
            import uvicorn

            db = app.bot_data["db"]
            admin_web_app = create_admin_web_app(db, settings)
            config = uvicorn.Config(
                admin_web_app,
                host=settings.admin_web_host,
                port=settings.admin_web_port,
                log_level="info",
            )
            admin_web_server = uvicorn.Server(config)
            admin_web_task = asyncio.create_task(admin_web_server.serve())
            log.info(
                "admin_web_started",
                host=settings.admin_web_host,
                port=settings.admin_web_port,
                url=f"http://{settings.admin_web_host}:{settings.admin_web_port}/admin/",
            )
        await _wait_for_shutdown_signal()
    finally:
        if admin_web_server is not None:
            admin_web_server.should_exit = True
        if admin_web_task is not None:
            try:
                await asyncio.wait_for(admin_web_task, timeout=10)
            except asyncio.TimeoutError:
                admin_web_task.cancel()
        if scheduler_started:
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
