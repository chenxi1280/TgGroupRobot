"""统一任务调度器核心"""

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
        self.last_run = None  # 上次运行时间
        self.next_run = None  # 下次运行时间
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
            log.info("task_started", task_name=self.name)
            await self.execute(app)
            self.last_run = start_time
            self.total_runs += 1
            self.error_count = 0  # 重置连续失败计数

            duration = (dt.datetime.now(dt.timezone.utc) - start_time).total_seconds()
            log.info(
                "task_completed",
                task_name=self.name,
                duration=duration,
                total_runs=self.total_runs,
            )
        except Exception as e:
            self.error_count += 1
            self.total_errors += 1
            duration = (dt.datetime.now(dt.timezone.utc) - start_time).total_seconds()
            log.error(
                "task_failed",
                task_name=self.name,
                error=str(e),
                error_count=self.error_count,
                total_errors=self.total_errors,
                duration=duration,
                exc_info=True,
            )
        finally:
            self.is_running = False

    def get_status(self) -> dict:
        """获取任务状态"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "interval": self.interval,
            "is_running": self.is_running,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "total_runs": self.total_runs,
            "total_errors": self.total_errors,
            "consecutive_errors": self.error_count,
        }


class Scheduler:
    """统一任务调度器"""

    def __init__(self, app: "Application"):
        """
        初始化调度器

        Args:
            app: Telegram Bot Application 实例
        """
        self.app = app
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
        log.info("task_registered", task_name=task.name, interval=task.interval)

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
        log.info("scheduler_started", task_count=len(self.tasks))

        # 为每个任务创建独立的异步任务
        for task in self.tasks.values():
            if task.enabled:
                async_task = asyncio.create_task(self._run_task_loop(task))
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

    async def _run_task_loop(self, task: ScheduledTask) -> None:
        """
        运行任务循环

        Args:
            task: 要运行的任务
        """
        task.next_run = dt.datetime.now(dt.timezone.utc)

        while self.running:
            try:
                # 等待到下次执行时间
                now = dt.datetime.now(dt.timezone.utc)
                if now >= task.next_run:
                    await task.run(self.app)

                    # 计算下次执行时间
                    task.next_run = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=task.interval)

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
        task.next_run = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=task.interval)

    def get_status(self) -> dict:
        """获取调度器状态"""
        return {
            "running": self.running,
            "tasks": {name: task.get_status() for name, task in self.tasks.items()},
        }
