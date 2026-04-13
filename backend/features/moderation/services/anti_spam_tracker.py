from __future__ import annotations

import asyncio
import datetime as dt
from collections import defaultdict, deque
from difflib import SequenceMatcher

from backend.features.moderation.services.anti_spam_types import SpamMessageRecord


class AntiSpamTracker:
    """反垃圾重复消息追踪器（内存实现）"""

    def __init__(self) -> None:
        self._records: dict[tuple[int, int], deque[SpamMessageRecord]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check_repeat(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        text_norm: str,
        max_messages: int,
        time_window_seconds: int,
    ) -> tuple[bool, list[int], str]:
        if not text_norm:
            return False, [], ""

        now = dt.datetime.now(dt.UTC)
        cutoff = now - dt.timedelta(seconds=max(time_window_seconds, 1))
        key = (chat_id, user_id)

        async with self._lock:
            queue = self._records[key]

            while queue and queue[0].at < cutoff:
                queue.popleft()

            queue.append(SpamMessageRecord(at=now, text_norm=text_norm, message_id=message_id))

            similar: list[SpamMessageRecord] = []
            for item in queue:
                if item.text_norm == text_norm:
                    similar.append(item)
                    continue
                if SequenceMatcher(None, item.text_norm, text_norm).ratio() >= 0.92:
                    similar.append(item)

            if len(similar) >= max(max_messages, 2):
                ids = [item.message_id for item in similar]
                return True, ids, f"repeat_count={len(similar)}"

            return False, [], ""

    async def cleanup_old_records(self, max_age_seconds: int = 600) -> None:
        now = dt.datetime.now(dt.UTC)
        cutoff = now - dt.timedelta(seconds=max_age_seconds)

        async with self._lock:
            to_remove: list[tuple[int, int]] = []
            for key, queue in self._records.items():
                while queue and queue[0].at < cutoff:
                    queue.popleft()
                if not queue:
                    to_remove.append(key)

            for key in to_remove:
                self._records.pop(key, None)
