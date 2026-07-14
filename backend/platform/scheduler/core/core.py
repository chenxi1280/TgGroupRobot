"""统一任务调度器核心。

生命周期边界：
- ``Scheduler.start()`` 为每个 ``enabled`` 任务创建独立 ``asyncio.Task``，
  按 ``interval`` 秒轮询执行 ``ScheduledTask.run()``。
- ``Scheduler.stop()`` 取消所有 ``asyncio.Task`` 并等待退出。
- ``ScheduledTask.run()`` 内部捕获 ``execute()`` 抛出的异常，按
  ``max_consecutive_failures`` 自动暂停连续失败的任务。
- 调度器在 schema gate 通过后启动（见 ``app/runtime.py``），确保任务
  执行时库结构已就绪。

子类只需实现 ``execute(app)``，不应自行捕获所有异常——``run()`` 已统一
记录 ``error`` + ``exc_info`` 并重置 ``error_count``。
"""

from __future__ import annotations

import asyncio
import datetime as dt
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from telegram.ext import Application

log = structlog.get_logger(__name__)


class ScheduledTask(ABC):
    """定时任务基类"""

    def __init__(
        self,
        name: str,
        interval: int,  # 执行间隔（秒）
        *,
        enabled: bool = True,
        max_consecutive_failures: int = 10,  # 连续失败多少次后暂停任务
    ):
        """
        初始化定时任务

        Args:
            name: 任务名称
            interval: 执行间隔（秒）
            enabled: 是否启用
            max_consecutive_failures: 连续失败多少次后暂停任务
        """
        self.name = name
        self.interval = interval
        self.enabled = enabled
        self.max_consecutive_failures = max_consecutive_failures

        # 运行状态
        self.last_run: dt.datetime | None = None  # 上次运行时间
        self.next_run: dt.datetime | None = None  # 下次运行时间
        self.last_success_at: dt.datetime | None = None
        self.last_failure_at: dt.datetime | None = None
        self.last_error: str | None = None
        self.error_count = 0  # 连续失败次数
        self.total_runs = 0  # 总运行次数
        self.total_errors = 0  # 总错误次数
        self.is_running = False  # 是否正在运行

    @abstractmethod
    async def execute(self, app: "Application") -> None:
        """
        任务执行逻辑（子类必须实现）

        Args:
            app: Telegram Bot Application 实例
        """
        pass

    async def run(self, app: "Application") -> None:
        """
        执行任务（带错误处理和监控）

        Args:
            app: Telegram Bot Application 实例
        """
        if not self.enabled:
            return

        if self.is_running:
            log.warning("task_skipped_already_running", task_name=self.name)
            return

        # 检查是否连续失败过多
        if self.error_count >= self.max_consecutive_failures:
            log.error(
                "task_paused_too_many_failures",
                task_name=self.name,
                error_count=self.error_count,
            )
            self.enabled = False
            return

        self.is_running = True
        start_time = dt.datetime.now(dt.timezone.utc)

        try:
            log.debug("task_started", task_name=self.name)
            await self.execute(app)
            self._record_success(start_time)
        except Exception as exc:
            self._record_failure(start_time, exc)
        finally:
            self.is_running = False

    def _record_success(self, start_time: dt.datetime) -> None:
        finished_at = dt.datetime.now(dt.timezone.utc)
        self.last_run = start_time
        self.last_success_at = finished_at
        self.last_error = None
        self.total_runs += 1
        self.error_count = 0
        log.debug(
            "task_completed",
            task_name=self.name,
            duration=(finished_at - start_time).total_seconds(),
            total_runs=self.total_runs,
        )

    def _record_failure(self, start_time: dt.datetime, error: Exception) -> None:
        finished_at = dt.datetime.now(dt.timezone.utc)
        self.last_failure_at = finished_at
        self.last_error = str(error)
        self.error_count += 1
        self.total_errors += 1
        log.error(
            "task_failed",
            task_name=self.name,
            error=str(error),
            error_count=self.error_count,
            total_errors=self.total_errors,
            duration=(finished_at - start_time).total_seconds(),
            exc_info=True,
        )

    def get_status(self) -> dict:
        """获取任务状态"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "interval": self.interval,
            "is_running": self.is_running,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
            "last_failure_at": (
                self.last_failure_at.isoformat() if self.last_failure_at else None
            ),
            "last_error": self.last_error,
            "total_runs": self.total_runs,
            "total_errors": self.total_errors,
            "consecutive_errors": self.error_count,
        }


class Scheduler:
    """统一任务调度器"""

    def __init__(
        self,
        app: "Application",
        *,
        run_immediately: bool = False,
        initial_stagger_seconds: float = 0.0,
    ):
        """
        初始化调度器

        Args:
            app: Telegram Bot Application 实例
            run_immediately: 是否在调度器启动后立刻执行首轮任务
            initial_stagger_seconds: 首轮任务之间的错峰间隔
        """
        self.app = app
        self.run_immediately = run_immediately
        self.initial_stagger_seconds = max(initial_stagger_seconds, 0.0)
        self.tasks: dict[str, ScheduledTask] = {}
        self.running = False
        self._task_tasks: dict[str, asyncio.Task] = {}  # 存储每个任务的 asyncio.Task

    def register_task(self, task: ScheduledTask) -> None:
        """
        注册任务

        Args:
            task: 要注册的任务
        """
        self.tasks[task.name] = task
        log.debug("task_registered", task_name=task.name, interval=task.interval)

    def register_tasks(self, tasks: list[ScheduledTask]) -> None:
        """
        批量注册任务

        Args:
            tasks: 要注册的任务列表
        """
        for task in tasks:
            self.register_task(task)

    async def start(self) -> None:
        """启动所有任务"""
        if self.running:
            log.warning("scheduler_already_running")
            return

        self.running = True
        log.info(
            "scheduler_started",
            task_count=len(self.tasks),
            run_immediately=self.run_immediately,
            initial_stagger_seconds=self.initial_stagger_seconds,
        )

        # 为每个任务创建独立的异步任务
        for index, task in enumerate(self.tasks.values()):
            if task.enabled:
                initial_delay = index * self.initial_stagger_seconds
                async_task = asyncio.create_task(
                    self._run_task_loop(task, initial_delay=initial_delay)
                )
                self._task_tasks[task.name] = async_task

    async def stop(self) -> None:
        """停止所有任务"""
        if not self.running:
            return

        log.info("scheduler_stopping")
        self.running = False

        # 取消所有任务
        for task_name, task in self._task_tasks.items():
            if not task.done():
                task.cancel()
                log.info("task_cancelled", task_name=task_name)

        # 等待所有任务完成
        if self._task_tasks:
            await asyncio.gather(*self._task_tasks.values(), return_exceptions=True)

        self._task_tasks.clear()
        log.info("scheduler_stopped")

    async def _run_task_loop(
        self, task: ScheduledTask, *, initial_delay: float = 0.0
    ) -> None:
        """
        运行任务循环

        Args:
            task: 要运行的任务
        """
        first_delay = (
            initial_delay if self.run_immediately else task.interval + initial_delay
        )
        task.next_run = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            seconds=first_delay
        )

        while self.running:
            try:
                # 等待到下次执行时间
                now = dt.datetime.now(dt.timezone.utc)
                if now >= task.next_run:
                    await task.run(self.app)

                    # 计算下次执行时间
                    task.next_run = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
                        seconds=task.interval
                    )

                # 睡眠一段时间再检查
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                log.info("task_loop_cancelled", task_name=task.name)
                break
            except Exception as e:
                log.error(
                    "task_loop_error",
                    task_name=task.name,
                    error=str(e),
                    exc_info=True,
                )
                # 出错后等待一段时间再继续
                await asyncio.sleep(5)

    async def run_task_now(self, task_name: str) -> None:
        """
        立即执行指定任务

        Args:
            task_name: 任务名称
        """
        if task_name not in self.tasks:
            log.error("task_not_found", task_name=task_name)
            return

        task = self.tasks[task_name]
        await task.run(self.app)
        # 重置下次执行时间
        task.next_run = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            seconds=task.interval
        )

    def get_status(self) -> dict:
        """获取调度器状态"""
        return {
            "running": self.running,
            "tasks": {name: task.get_status() for name, task in self.tasks.items()},
        }
