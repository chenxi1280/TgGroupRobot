from __future__ import annotations

import pytest
from telegram.error import Forbidden, RetryAfter, TimedOut

from backend.features.garage.forward_delivery_executor import (
    GarageForwardPlan,
    TelegramGarageForwardExecutor,
)


SNAPSHOT = {
    "inline_keyboard": [[{"text": "详情", "url": "https://example.com"}]],
}


def _plan() -> GarageForwardPlan:
    return GarageForwardPlan(
        delivery_id=1,
        message_map_id=2,
        chat_id=-20001,
        source_channel_id=-10001,
        source_message_id=321,
        reply_markup_snapshot=SNAPSHOT,
    )


class FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    async def copy_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return type("Copied", (), {"message_id": 999})()


@pytest.mark.asyncio
async def test_executor_restores_full_reply_markup_snapshot() -> None:
    bot = FakeBot()

    outcome = await TelegramGarageForwardExecutor(bot).execute(_plan())

    assert outcome.status.value == "succeeded"
    assert outcome.message_id == 999
    assert bot.calls[0]["reply_markup"].to_dict() == SNAPSHOT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (RetryAfter(30), "retryable_failed"),
        (Forbidden("no access"), "permanent_failed"),
        (TimedOut(), "uncertain"),
    ],
)
async def test_executor_classifies_telegram_failures(error: Exception, status: str) -> None:
    outcome = await TelegramGarageForwardExecutor(FakeBot(error)).execute(_plan())

    assert outcome.status.value == status
