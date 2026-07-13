from __future__ import annotations

import importlib

import pytest
from telegram.error import Forbidden, RetryAfter, TimedOut


executor_module = importlib.import_module("backend.features.verification.timeout_executor")


class FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def restrict_chat_member(self, **kwargs):
        self.calls.append(("restrict", kwargs))
        if self.error is not None:
            raise self.error

    async def ban_chat_member(self, **kwargs):
        self.calls.append(("ban", kwargs))
        if self.error is not None:
            raise self.error


def _plan(action: str = "mute"):
    plan_type = getattr(executor_module, "VerificationTimeoutPlan", None)
    assert plan_type is not None
    return plan_type(
        challenge_id=1,
        attempt_id=2,
        chat_id=-100123,
        user_id=99,
        action=action,
        duration_seconds=3600,
    )


@pytest.mark.asyncio
async def test_executor_returns_success_after_mute() -> None:
    executor_type = getattr(executor_module, "TelegramVerificationTimeoutExecutor", None)

    assert executor_type is not None
    bot = FakeBot()
    outcome = await executor_type(bot).execute(_plan())

    assert outcome.status.value == "succeeded"
    assert bot.calls[0][0] == "restrict"
    assert bot.calls[0][1]["until_date"] is not None


@pytest.mark.asyncio
async def test_executor_classifies_retry_after_as_retryable() -> None:
    executor_type = getattr(executor_module, "TelegramVerificationTimeoutExecutor", None)

    assert executor_type is not None
    outcome = await executor_type(FakeBot(RetryAfter(30))).execute(_plan())

    assert outcome.status.value == "retryable_failed"
    assert outcome.error_code == "telegram_retry_after"


@pytest.mark.asyncio
async def test_executor_classifies_permission_failure_as_permanent() -> None:
    executor_type = getattr(executor_module, "TelegramVerificationTimeoutExecutor", None)

    assert executor_type is not None
    outcome = await executor_type(FakeBot(Forbidden("not enough rights"))).execute(_plan("kick"))

    assert outcome.status.value == "permanent_failed"
    assert outcome.error_code == "telegram_forbidden"


@pytest.mark.asyncio
async def test_executor_classifies_started_timeout_as_uncertain() -> None:
    executor_type = getattr(executor_module, "TelegramVerificationTimeoutExecutor", None)

    assert executor_type is not None
    outcome = await executor_type(FakeBot(TimedOut())).execute(_plan("unrestrict"))

    assert outcome.status.value == "uncertain"
    assert outcome.error_code == "telegram_network_unknown"
