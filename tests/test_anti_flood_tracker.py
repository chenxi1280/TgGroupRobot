from __future__ import annotations

import asyncio

import pytest

from bot.services.moderation.anti_flood_service import AntiFloodTracker


@pytest.mark.asyncio
async def test_muted_state_expires_and_cleanup_removes_empty_record():
    tracker = AntiFloodTracker()
    chat_id = -10001
    user_id = 20001

    await tracker.add_message(chat_id, user_id, 1)
    messages = await tracker.get_and_clear_messages(chat_id, user_id)
    assert messages == [1]

    await tracker.mark_muted(chat_id, user_id, duration_seconds=1)
    assert await tracker.is_muted(chat_id, user_id) is True

    await asyncio.sleep(1.1)
    assert await tracker.is_muted(chat_id, user_id) is False

    await tracker.cleanup_old_records(max_age_seconds=1)
    assert (chat_id, user_id) not in tracker._records
