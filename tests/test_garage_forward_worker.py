from __future__ import annotations

import datetime as dt

import pytest

from backend.features.garage.forward_delivery_executor import GarageForwardPlan
from backend.features.garage.forward_delivery_worker import (
    GarageForwardBatchError,
    GarageForwardWorker,
    GarageWorkerDependencies,
)
from backend.platform.delivery import DeliveryOutcome


NOW = dt.datetime(2026, 7, 13, 12, tzinfo=dt.UTC)


def _plan(delivery_id: int) -> GarageForwardPlan:
    return GarageForwardPlan(
        delivery_id=delivery_id,
        message_map_id=delivery_id + 100,
        chat_id=-20000 - delivery_id,
        source_channel_id=-10001,
        source_message_id=300 + delivery_id,
        reply_markup_snapshot=None,
    )


class FakeStore:
    def __init__(self, plans: tuple[GarageForwardPlan, ...]) -> None:
        self.plans = plans
        self.events: list[tuple[str, int | None]] = []
        self.finalize_failures: set[int] = set()

    async def recover_expired_leases(self, now: dt.datetime) -> int:
        self.events.append(("recover", None))
        return 0

    async def claim_due(self, now: dt.datetime, lease_until: dt.datetime, *, limit: int):
        self.events.append(("claim", None))
        return self.plans

    async def mark_send_started(self, plan: GarageForwardPlan, now: dt.datetime) -> None:
        self.events.append(("started", plan.delivery_id))

    async def finalize(self, plan: GarageForwardPlan, outcome: DeliveryOutcome, *, now: dt.datetime) -> None:
        self.events.append(("finalize", plan.delivery_id))
        if plan.delivery_id in self.finalize_failures:
            raise RuntimeError("database finalize failed")

    async def mark_finalize_uncertain(self, plan: GarageForwardPlan, error: Exception, *, now: dt.datetime) -> None:
        self.events.append(("uncertain", plan.delivery_id))


class FakeExecutor:
    def __init__(self, outcomes: dict[int, DeliveryOutcome], events) -> None:
        self.outcomes = outcomes
        self.events = events

    async def execute(self, plan: GarageForwardPlan) -> DeliveryOutcome:
        self.events.append(("execute", plan.delivery_id))
        return self.outcomes[plan.delivery_id]


def _worker(store: FakeStore, outcomes: dict[int, DeliveryOutcome]) -> GarageForwardWorker:
    return GarageForwardWorker(GarageWorkerDependencies(
        store=store,
        executor=FakeExecutor(outcomes, store.events),
        clock=lambda: NOW,
    ))


@pytest.mark.asyncio
async def test_worker_marks_started_before_copy_and_finalize() -> None:
    store = FakeStore((_plan(1),))

    summary = await _worker(store, {1: DeliveryOutcome.success(900)}).run()

    assert store.events == [
        ("recover", None),
        ("claim", None),
        ("started", 1),
        ("execute", 1),
        ("finalize", 1),
    ]
    assert summary.succeeded == 1


@pytest.mark.asyncio
async def test_worker_isolates_finalize_failure_and_marks_uncertain() -> None:
    store = FakeStore((_plan(1), _plan(2)))
    store.finalize_failures.add(1)
    worker = _worker(store, {
        1: DeliveryOutcome.success(901),
        2: DeliveryOutcome.success(902),
    })

    with pytest.raises(GarageForwardBatchError):
        await worker.run()

    assert ("uncertain", 1) in store.events
    assert ("execute", 2) in store.events


@pytest.mark.asyncio
async def test_worker_reports_non_success_outcome_as_unhealthy_batch() -> None:
    store = FakeStore((_plan(1),))
    outcome = DeliveryOutcome.uncertain("network", "unknown result")

    with pytest.raises(GarageForwardBatchError):
        await _worker(store, {1: outcome}).run()

    assert store.events.count(("execute", 1)) == 1
