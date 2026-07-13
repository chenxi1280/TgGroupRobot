from __future__ import annotations

import datetime as dt
import importlib

import pytest

from backend.features.verification.timeout_executor import VerificationTimeoutPlan
from backend.platform.delivery import DeliveryOutcome


worker_module = importlib.import_module("backend.features.verification.timeout_worker")


NOW = dt.datetime(2026, 7, 14, tzinfo=dt.UTC)


def _plan(attempt_id: int, action: str = "mute") -> VerificationTimeoutPlan:
    return VerificationTimeoutPlan(
        challenge_id=attempt_id,
        attempt_id=attempt_id,
        chat_id=-100123,
        user_id=attempt_id,
        action=action,
        duration_seconds=3600,
    )


class FakeStore:
    def __init__(self, claims: tuple[VerificationTimeoutPlan, ...]) -> None:
        self.claims = claims
        self.events: list[tuple[str, int | None]] = []
        self.finalized: list[tuple[int, DeliveryOutcome]] = []
        self.fail_finalize_for: set[int] = set()

    async def recover_expired_leases(self, now: dt.datetime) -> int:
        self.events.append(("recover", None))
        return 0

    async def claim_due(self, now: dt.datetime, lease_until: dt.datetime, *, limit: int):
        self.events.append(("claim", None))
        return self.claims

    async def mark_send_started(self, plan: VerificationTimeoutPlan, now: dt.datetime) -> None:
        self.events.append(("started", plan.attempt_id))

    async def finalize(
        self,
        plan: VerificationTimeoutPlan,
        outcome: DeliveryOutcome,
        *,
        now: dt.datetime,
    ) -> None:
        self.events.append(("finalize", plan.attempt_id))
        if plan.attempt_id in self.fail_finalize_for:
            raise RuntimeError(f"finalize failed: {plan.attempt_id}")
        self.finalized.append((plan.attempt_id, outcome))


class FakeExecutor:
    def __init__(self, outcomes: dict[int, DeliveryOutcome], events: list[tuple[str, int | None]]) -> None:
        self.outcomes = outcomes
        self.events = events

    async def execute(self, plan: VerificationTimeoutPlan) -> DeliveryOutcome:
        self.events.append(("execute", plan.attempt_id))
        return self.outcomes[plan.attempt_id]


def _build_worker(store: FakeStore, outcomes: dict[int, DeliveryOutcome]):
    dependencies_type = getattr(worker_module, "WorkerDependencies", None)
    worker_type = getattr(worker_module, "VerificationTimeoutWorker", None)

    assert dependencies_type is not None
    assert worker_type is not None
    executor = FakeExecutor(outcomes, store.events)
    return worker_type(
        dependencies_type(
            store=store,
            executor=executor,
            clock=lambda: NOW,
        )
    )


@pytest.mark.asyncio
async def test_worker_marks_send_started_before_execution_and_finalization() -> None:
    plan = _plan(1)
    store = FakeStore((plan,))
    worker = _build_worker(store, {1: DeliveryOutcome.success()})

    summary = await worker.run()

    assert store.events == [
        ("recover", None),
        ("claim", None),
        ("started", 1),
        ("execute", 1),
        ("finalize", 1),
    ]
    assert summary.succeeded == 1
    assert summary.failed == 0


@pytest.mark.asyncio
async def test_worker_persists_retryable_failure_and_reports_unhealthy_batch() -> None:
    error_type = getattr(worker_module, "VerificationTimeoutBatchError", None)

    assert error_type is not None
    plan = _plan(1)
    store = FakeStore((plan,))
    outcome = DeliveryOutcome.retryable_failure("rate_limited", "retry later")
    worker = _build_worker(store, {1: outcome})

    with pytest.raises(error_type):
        await worker.run()

    assert store.finalized == [(1, outcome)]


@pytest.mark.asyncio
async def test_worker_persists_uncertain_result_without_automatic_replay() -> None:
    error_type = getattr(worker_module, "VerificationTimeoutBatchError", None)

    assert error_type is not None
    plan = _plan(1)
    store = FakeStore((plan,))
    outcome = DeliveryOutcome.uncertain("network", "result unknown")
    worker = _build_worker(store, {1: outcome})

    with pytest.raises(error_type):
        await worker.run()

    assert store.finalized == [(1, outcome)]
    assert store.events.count(("execute", 1)) == 1


@pytest.mark.asyncio
async def test_worker_isolates_one_finalize_failure_and_processes_remaining_items() -> None:
    error_type = getattr(worker_module, "VerificationTimeoutBatchError", None)

    assert error_type is not None
    first = _plan(1)
    second = _plan(2)
    store = FakeStore((first, second))
    store.fail_finalize_for.add(1)
    worker = _build_worker(
        store,
        {1: DeliveryOutcome.success(), 2: DeliveryOutcome.success()},
    )

    with pytest.raises(error_type):
        await worker.run()

    assert ("execute", 2) in store.events
    assert store.finalized == [(2, DeliveryOutcome.success())]


@pytest.mark.asyncio
async def test_worker_no_action_completes_without_send_started_marker() -> None:
    plan = _plan(1, action="none")
    store = FakeStore((plan,))
    worker = _build_worker(store, {1: DeliveryOutcome.success()})

    summary = await worker.run()

    assert ("started", 1) not in store.events
    assert summary.succeeded == 1
