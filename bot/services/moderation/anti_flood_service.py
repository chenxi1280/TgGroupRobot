from __future__ import annotations

import asyncio
import datetime as dt
import structlog
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from telegram import Bot


log = structlog.get_logger(__name__)


@dataclass
class FloodRecord:
    """用户消息记录"""
    chat_id: int
    user_id: int
    message_ids: list[int]  # 消息ID列表，用于删除
    timestamps: deque[dt.datetime] = field(default_factory=deque)
    is_muted: bool = False  # 是否已被禁言


@dataclass
class FloodDetectionResult:
    """刷屏检测结果"""
    is_flooding: bool
    message_count: int
    time_span: float  # 秒
    action: Literal["none", "delete", "mute", "ban"]


class AntiFloodTracker:
    """反刷屏追踪器（内存存储）"""

    def __init__(self):
        # {(chat_id, user_id): FloodRecord}
        self._records: dict[tuple[int, int], FloodRecord] = {}
        self._lock = asyncio.Lock()

    def _get_key(self, chat_id: int, user_id: int) -> tuple[int, int]:
        return (chat_id, user_id)

    async def add_message(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
    ) -> FloodRecord:
        """添加消息记录"""
        async with self._lock:
            key = self._get_key(chat_id, user_id)
            now = dt.datetime.now(dt.UTC)

            if key not in self._records:
                self._records[key] = FloodRecord(
                    chat_id=chat_id,
                    user_id=user_id,
                    message_ids=[],
                    timestamps=deque(),
                )

            record = self._records[key]
            record.message_ids.append(message_id)
            record.timestamps.append(now)

            return record

    async def check_flood(
        self,
        chat_id: int,
        user_id: int,
        max_messages: int,
        time_window_seconds: int,
    ) -> FloodDetectionResult:
        """检测是否刷屏"""
        async with self._lock:
            key = self._get_key(chat_id, user_id)

            if key not in self._records:
                return FloodDetectionResult(
                    is_flooding=False,
                    message_count=0,
                    time_span=0.0,
                    action="none",
                )

            record = self._records[key]
            now = dt.datetime.now(dt.UTC)

            # 清理过期的时间戳
            cutoff_time = now - dt.timedelta(seconds=time_window_seconds)
            while record.timestamps and record.timestamps[0] < cutoff_time:
                record.timestamps.popleft()
                # 同时清理对应的消息ID（只保留最新的）
                if record.message_ids:
                    record.message_ids.pop(0)

            message_count = len(record.timestamps)

            if message_count >= max_messages:
                # 计算时间跨度
                if len(record.timestamps) >= 2:
                    time_span = (record.timestamps[-1] - record.timestamps[0]).total_seconds()
                else:
                    time_span = 0.0

                return FloodDetectionResult(
                    is_flooding=True,
                    message_count=message_count,
                    time_span=time_span,
                    action="none",  # 由调用者决定动作
                )

            return FloodDetectionResult(
                is_flooding=False,
                message_count=message_count,
                time_span=0.0,
                action="none",
            )

    async def get_and_clear_messages(
        self,
        chat_id: int,
        user_id: int,
    ) -> list[int]:
        """获取并清空用户的违规消息ID"""
        async with self._lock:
            key = self._get_key(chat_id, user_id)
            if key not in self._records:
                return []

            record = self._records[key]
            message_ids = record.message_ids.copy()
            # 清空记录
            record.message_ids.clear()
            record.timestamps.clear()
            return message_ids

    async def mark_muted(self, chat_id: int, user_id: int, muted: bool = True):
        """标记用户已被禁言（避免重复禁言）"""
        async with self._lock:
            key = self._get_key(chat_id, user_id)
            if key in self._records:
                self._records[key].is_muted = muted

    async def is_muted(self, chat_id: int, user_id: int) -> bool:
        """检查用户是否已被禁言"""
        async with self._lock:
            key = self._get_key(chat_id, user_id)
            return self._records.get(key, FloodRecord(chat_id, user_id, [])).is_muted

    async def cleanup_old_records(self, max_age_seconds: int = 300):
        """清理旧的记录"""
        async with self._lock:
            now = dt.datetime.now(dt.UTC)
            cutoff_time = now - dt.timedelta(seconds=max_age_seconds)

            keys_to_delete = []
            for key, record in self._records.items():
                # 如果记录超过指定时间没有活动，删除
                if record.timestamps and record.timestamps[-1] < cutoff_time:
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                del self._records[key]


# 全局追踪器实例
_tracker = AntiFloodTracker()


def get_tracker() -> AntiFloodTracker:
    """获取全局追踪器"""
    return _tracker


async def execute_flood_punishment(
    bot: Bot,
    chat_id: int,
    user_id: int,
    action: str,
    mute_duration: int = 60,
) -> bool:
    """执行刷屏惩罚"""
    try:
        if action == "delete":
            # 只删除消息，不禁言
            message_ids = await _tracker.get_and_clear_messages(chat_id, user_id)
            for msg_id in message_ids:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception as e:
                    log.warning("delete_message_failed", chat_id=chat_id, message_id=msg_id, error=str(e))
            return True

        elif action == "mute":
            # 禁言并删除消息
            message_ids = await _tracker.get_and_clear_messages(chat_id, user_id)
            for msg_id in message_ids:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception as e:
                    log.warning("delete_message_failed", chat_id=chat_id, message_id=msg_id, error=str(e))

            # 检查是否已经禁言，避免重复
            if await _tracker.is_muted(chat_id, user_id):
                return True

            try:
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions={"can_send_messages": False, "can_send_media_messages": False},
                    until_date=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=mute_duration),
                )
                await _tracker.mark_muted(chat_id, user_id, True)
                return True
            except Exception as e:
                log.warning("ban_chat_member_failed", chat_id=chat_id, user_id=user_id, error=str(e))
                return False

        elif action == "ban":
            # 封禁并删除消息
            message_ids = await _tracker.get_and_clear_messages(chat_id, user_id)
            for msg_id in message_ids:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception as e:
                    log.warning("delete_message_failed", chat_id=chat_id, message_id=msg_id, error=str(e))

            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                return True
            except Exception as e:
                log.warning("ban_chat_member_failed", chat_id=chat_id, user_id=user_id, error=str(e))
                return False

    except Exception:
        return False

    return False


async def anti_flood_cleanup_job(app) -> None:
    """清理反刷屏追踪器中的旧记录

    Args:
        app: Telegram Bot 应用实例
    """
    import structlog

    log = structlog.get_logger(__name__)
    try:
        await _tracker.cleanup_old_records(max_age_seconds=300)
        log.info("anti_flood_cleanup_completed")
    except Exception as e:
        log.error("anti_flood_cleanup_failed", error=str(e))
