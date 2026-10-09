"""PostgreSQL 会话级 advisory lock，保证多副本只有一个 leader 跑 bot/调度器。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

log = structlog.get_logger(__name__)

# 固定 64-bit key 空间，避免与业务 advisory lock 冲突
_LEADER_LOCK_KEY = 0x7467_6772_6F62_6F74  # "tggrobot"
LEADER_HEALTH_INTERVAL_SECONDS = 5.0


@dataclass
class LeaderLock:
    engine: AsyncEngine
    connection: AsyncConnection | None = None
    held: bool = False
    lost_event: asyncio.Event = field(default_factory=asyncio.Event)
    monitor_task: asyncio.Task | None = None

    async def acquire(self, *, blocking: bool = True, timeout_seconds: float = 30.0) -> bool:
        if self.held:
            return True
        self.connection = await self.engine.connect()
        try:
            if blocking:
                await asyncio.wait_for(
                    self.connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _LEADER_LOCK_KEY}),
                    timeout=timeout_seconds,
                )
                self.held = True
            else:
                result = await self.connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": _LEADER_LOCK_KEY},
                )
                self.held = bool(result.scalar())
                if not self.held:
                    await self.connection.close()
                    self.connection = None
            if self.held:
                await self.connection.commit()
            log.info("leader_lock_acquire", held=self.held, blocking=blocking)
            return self.held
        except Exception:
            if self.connection is not None:
                await self.connection.close()
                self.connection = None
            self.held = False
            raise

    def start_monitor(
        self,
        *,
        interval_seconds: float = LEADER_HEALTH_INTERVAL_SECONDS,
    ) -> None:
        if not self.held or self.connection is None:
            raise RuntimeError("cannot monitor a leader lock that is not held")
        if self.monitor_task is not None and not self.monitor_task.done():
            return
        self.monitor_task = asyncio.create_task(
            self._monitor_connection(interval_seconds=interval_seconds)
        )

    async def _monitor_connection(self, *, interval_seconds: float) -> None:
        try:
            while self.held and self.connection is not None:
                await asyncio.sleep(max(interval_seconds, 0.0))
                await self.connection.execute(text("SELECT 1"))
                await self.connection.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.held = False
            self.lost_event.set()
            log.error("leader_lock_lost", error=str(exc), exc_info=True)

    async def wait_until_lost(self) -> None:
        await self.lost_event.wait()

    async def _stop_monitor(self) -> None:
        task = self.monitor_task
        self.monitor_task = None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def release(self) -> None:
        await self._stop_monitor()
        if self.connection is None:
            self.held = False
            return
        try:
            if self.held:
                await self.connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": _LEADER_LOCK_KEY},
                )
                await self.connection.commit()
        except Exception as exc:
            log.warning("leader_lock_release_failed", error=str(exc))
        finally:
            await self.connection.close()
            self.connection = None
            self.held = False
            log.info("leader_lock_released")


async def acquire_bot_leader_lock(engine: AsyncEngine, *, required: bool = True) -> LeaderLock | None:
    """
    获取 bot 进程 leader 锁。

    required=True 时拿不到锁直接抛错退出，避免双实例双调度。
    """
    lock = LeaderLock(engine=engine)
    held = await lock.acquire(blocking=False)
    if held:
        return lock
    if required:
        raise RuntimeError(
            "另一个 TgGroupRobot 实例已持有 leader lock。"
            "多副本部署时仅允许一个进程启动 polling/调度器。"
        )
    return None
