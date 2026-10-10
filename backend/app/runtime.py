from __future__ import annotations

import asyncio
import signal
import sys
import time
from dataclasses import dataclass

from telegram import Update

from backend.app.bootstrap import (
    _check_single_instance,
    _validate_schema_or_exit,
    build_application,
    log,
)
from backend.platform.runtime.leader_lock import LeaderLock, acquire_bot_leader_lock
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

    from backend.platform.scheduler.tasks.mall_notification_task import MallNotificationTask
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
        MallNotificationTask(),
        TeacherSearchTask(),
        GarageForwardRetryTask(),
    ])


async def _wait_for_shutdown_signal(leader_lock: LeaderLock) -> None:
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

    stop_task = asyncio.create_task(stop_event.wait())
    leader_lost_task = asyncio.create_task(leader_lock.wait_until_lost())
    try:
        done, pending = await asyncio.wait(
            {stop_task, leader_lost_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if leader_lost_task in done:
            raise RuntimeError("database leader lock lost")
    finally:
        for shutdown_signal in handled_signals:
            loop.remove_signal_handler(shutdown_signal)


async def _start_admin_web(app, settings):
    if not getattr(settings, "admin_web_enabled", True):
        return None, None
    import uvicorn

    from backend.features.web_admin.app import create_admin_web_app

    admin_web_app = create_admin_web_app(app.bot_data["db"], settings)
    if "scheduler" in app.bot_data:
        admin_web_app.state.scheduler = app.bot_data["scheduler"]
    config = uvicorn.Config(
        admin_web_app,
        host=settings.admin_web_host,
        port=settings.admin_web_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    log.info(
        "admin_web_started",
        host=settings.admin_web_host,
        port=settings.admin_web_port,
        url=f"http://{settings.admin_web_host}:{settings.admin_web_port}/admin/",
    )
    return server, task


async def _stop_admin_web(server, task: asyncio.Task | None) -> None:
    if server is not None:
        server.should_exit = True
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=10)
    except asyncio.TimeoutError:
        task.cancel()


async def _acquire_leader_or_exit(db) -> LeaderLock:
    try:
        lock = await acquire_bot_leader_lock(db.engine, required=True)
    except RuntimeError as exc:
        log.error("leader_lock_unavailable", error=str(exc))
        raise SystemExit(2) from exc
    assert lock is not None
    return lock


@dataclass
class RuntimeState:
    initialized: bool = False
    started: bool = False
    polling_started: bool = False
    scheduler_started: bool = False
    admin_web_server: object | None = None
    admin_web_task: asyncio.Task | None = None


async def _start_runtime_services(app, scheduler, settings, *, state: RuntimeState) -> None:
    await app.initialize()
    state.initialized = True
    await app.start()
    state.started = True
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    state.polling_started = True
    _register_scheduler_tasks(scheduler)
    await scheduler.start()
    state.scheduler_started = True
    state.admin_web_server, state.admin_web_task = await _start_admin_web(app, settings)


async def _stop_runtime_services(
    app,
    *,
    scheduler: Scheduler,
    state: RuntimeState,
    leader_lock: LeaderLock | None,
) -> None:
    await _stop_admin_web(state.admin_web_server, state.admin_web_task)
    if state.scheduler_started:
        await scheduler.stop()
    if state.polling_started and app.updater is not None:
        await app.updater.stop()
    if state.started:
        await app.stop()
    if state.initialized:
        await app.shutdown()
    if leader_lock is not None:
        await leader_lock.release()


async def run_bot_with_scheduler() -> None:
    startup_started = time.perf_counter()
    app = build_application()
    log.info("bot_starting")

    settings = app.bot_data["settings"]
    db = app.bot_data["db"]
    scheduler = Scheduler(
        app,
        run_immediately=getattr(settings, "scheduler_run_immediately", False),
        initial_stagger_seconds=getattr(settings, "scheduler_initial_stagger_seconds", 0.0),
    )
    app.bot_data["scheduler"] = scheduler
    leader_lock = await _acquire_leader_or_exit(db)
    state = RuntimeState()
    try:
        leader_lock.start_monitor()
        await _validate_schema_or_exit(app)
        await _start_runtime_services(app, scheduler, settings, state=state)
        log.info(
            "polling_started",
            allowed_updates="ALL_TYPES",
            startup_seconds=round(time.perf_counter() - startup_started, 3),
        )
        await _wait_for_shutdown_signal(leader_lock)
    finally:
        await _stop_runtime_services(
            app,
            scheduler=scheduler,
            state=state,
            leader_lock=leader_lock,
        )


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
