from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from telegram.error import NetworkError, RetryAfter

from backend.features.automation.scheduled_delivery_executor import (
    ScheduledDeliveryPlan,
    TelegramScheduledDeliveryExecutor,
)
from backend.features.automation.scheduled_delivery_worker import (
    ScheduledDeliveryBatchError,
    ScheduledDeliveryWorker,
    ScheduledWorkerDependencies,
)
from backend.features.automation.scheduled_occurrence_repository import (
    finalize_occurrence,
    recover_expired_occurrence,
    snapshot_task,
)
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus, RetryPolicy

NOW = dt.datetime(2026, 7, 13, tzinfo=dt.UTC)


def _snapshot(**changes):
    value = {
        "title": "测试任务",
        "chat_id": -1001,
        "delete_previous": False,
        "last_sent_message_id": None,
        "pin_message": False,
        "text": "你好",
        "parse_mode": "HTML",
        "media_type": "none",
        "media_file_id": None,
        "buttons": [],
    }
    value.update(changes)
    return value


def _plan(**changes):
    value = {
        "occurrence_id": 11,
        "task_id": "8d886979-b6b6-4c9c-9077-66f96ee87e39",
        "chat_id": -1001,
        "snapshot": _snapshot(),
    }
    value.update(changes)
    return ScheduledDeliveryPlan(**value)


class _Bot:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(("send", kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(message_id=123)

    async def delete_message(self, **kwargs):
        self.calls.append(("delete", kwargs))

    async def pin_chat_message(self, **kwargs):
        self.calls.append(("pin", kwargs))


@pytest.mark.asyncio
async def test_executor_sends_snapshot_and_returns_message_id() -> None:
    bot = _Bot()
    executor = TelegramScheduledDeliveryExecutor(SimpleNamespace(bot=bot))

    outcome = await executor.execute(_plan())

    assert outcome == DeliveryOutcome.success(message_id=123)
    assert bot.calls[0][1]["text"] == "你好"


@pytest.mark.asyncio
async def test_executor_classifies_retry_after_and_network_unknown() -> None:
    retry = await TelegramScheduledDeliveryExecutor(
        SimpleNamespace(bot=_Bot(RetryAfter(3)))
    ).execute(_plan())
    unknown = await TelegramScheduledDeliveryExecutor(
        SimpleNamespace(bot=_Bot(NetworkError("lost")))
    ).execute(_plan())

    assert retry.status is DeliveryStatus.retryable_failed
    assert unknown.status is DeliveryStatus.uncertain


class _Store:
    def __init__(self) -> None:
        self.finalized = []
        self.started = []
        self.uncertain = []

    async def create_due_occurrences(self, now):
        return 1

    async def recover_expired_leases(self, now):
        return 0

    async def claim_due(self, now, lease_until, *, limit):
        return (_plan(),)

    async def mark_send_started(self, plan, now):
        self.started.append(plan.occurrence_id)

    async def finalize(self, plan, outcome, *, now):
        self.finalized.append(outcome)

    async def mark_finalize_uncertain(self, plan, error, *, now):
        self.uncertain.append(str(error))


class _Executor:
    def __init__(self, outcome: DeliveryOutcome) -> None:
        self.outcome = outcome

    async def execute(self, plan):
        return self.outcome


@pytest.mark.asyncio
async def test_worker_marks_send_started_and_reports_success() -> None:
    store = _Store()
    worker = ScheduledDeliveryWorker(ScheduledWorkerDependencies(
        store=store,
        executor=_Executor(DeliveryOutcome.success(message_id=123)),
        clock=lambda: NOW,
    ))

    summary = await worker.run()

    assert (summary.created, summary.claimed, summary.succeeded) == (1, 1, 1)
    assert store.started == [11]


@pytest.mark.asyncio
async def test_worker_surfaces_non_success_to_scheduler_health() -> None:
    worker = ScheduledDeliveryWorker(ScheduledWorkerDependencies(
        store=_Store(),
        executor=_Executor(DeliveryOutcome.permanent_failure("forbidden", "no access")),
        clock=lambda: NOW,
    ))

    with pytest.raises(ScheduledDeliveryBatchError) as error:
        await worker.run()

    assert error.value.summary.failed == 1


def test_expired_lease_after_send_becomes_uncertain() -> None:
    occurrence = SimpleNamespace(
        send_started_at=NOW,
        status="processing",
        next_retry_at=None,
        lease_until=NOW,
        error_code=None,
        error_message=None,
        completed_at=None,
        success=None,
    )

    recover_expired_occurrence(occurrence, NOW)

    assert occurrence.status == DeliveryStatus.uncertain.value
    assert occurrence.error_code == "lease_expired_after_send"


def test_retryable_outcome_uses_backoff_and_success_updates_task() -> None:
    occurrence = SimpleNamespace(
        id=7,
        attempt_count=1,
        status="processing",
        next_retry_at=None,
        lease_until=NOW,
        error_code=None,
        error_message=None,
        completed_at=None,
        message_id=None,
        sent_at=None,
        success=None,
    )
    task = SimpleNamespace(last_sent_message_id=None)
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=60, max_delay_seconds=60)

    finalize_occurrence(
        occurrence,
        task,
        DeliveryOutcome.retryable_failure("rate_limit", "later"),
        now=NOW,
        retry_policy=policy,
    )
    assert occurrence.status == DeliveryStatus.retryable_failed.value
    assert occurrence.next_retry_at == NOW + dt.timedelta(seconds=60)

    finalize_occurrence(
        occurrence,
        task,
        DeliveryOutcome.success(message_id=99),
        now=NOW,
        retry_policy=policy,
    )
    assert task.last_sent_message_id == 99
    assert occurrence.success is True


def test_snapshot_is_complete_and_log_model_has_occurrence_fields() -> None:
    task = SimpleNamespace(**_snapshot())

    assert snapshot_task(task) == _snapshot()
    columns = ScheduledMessageLog.__table__.columns
    assert {"run_key", "scheduled_for", "content_snapshot", "status", "lease_until"} <= set(columns.keys())
