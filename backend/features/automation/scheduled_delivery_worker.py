from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from backend.features.automation.scheduled_delivery_executor import (
    ScheduledDeliveryExecutor,
    ScheduledDeliveryPlan,
)
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus

DEFAULT_BATCH_SIZE = 100
DEFAULT_LEASE_SECONDS = 120


class ScheduledOccurrenceStore(Protocol):
    async def create_due_occurrences(self, now: dt.datetime) -> int: ...
    async def recover_expired_leases(self, now: dt.datetime) -> int: ...
    async def claim_due(self, now: dt.datetime, lease_until: dt.datetime, *, limit: int): ...
    async def mark_send_started(self, plan: ScheduledDeliveryPlan, now: dt.datetime) -> None: ...
    async def finalize(self, plan, outcome: DeliveryOutcome, *, now: dt.datetime) -> None: ...
    async def mark_finalize_uncertain(self, plan, error: Exception, *, now: dt.datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class ScheduledWorkerConfig:
    batch_size: int = DEFAULT_BATCH_SIZE
    lease_seconds: int = DEFAULT_LEASE_SECONDS


@dataclass(frozen=True, slots=True)
class ScheduledWorkerDependencies:
    store: ScheduledOccurrenceStore
    executor: ScheduledDeliveryExecutor
    clock: Callable[[], dt.datetime]
    config: ScheduledWorkerConfig = field(default_factory=ScheduledWorkerConfig)


@dataclass(frozen=True, slots=True)
class ScheduledWorkerSummary:
    created: int
    claimed: int
    succeeded: int
    failed: int
    recovered: int


class ScheduledDeliveryBatchError(RuntimeError):
    def __init__(self, summary: ScheduledWorkerSummary, errors: tuple[Exception, ...]) -> None:
        super().__init__(
            f"scheduled delivery batch failed: claimed={summary.claimed}, "
            f"failed={summary.failed}, errors={len(errors)}"
        )
        self.summary = summary
        self.errors = errors


class ScheduledDeliveryWorker:
    def __init__(self, dependencies: ScheduledWorkerDependencies) -> None:
        self._dependencies = dependencies

    async def run(self) -> ScheduledWorkerSummary:
        now = self._dependencies.clock()
        created = await self._dependencies.store.create_due_occurrences(now)
        recovered = await self._dependencies.store.recover_expired_leases(now)
        lease_until = now + dt.timedelta(seconds=self._dependencies.config.lease_seconds)
        plans = await self._dependencies.store.claim_due(
            now,
            lease_until,
            limit=self._dependencies.config.batch_size,
        )
        succeeded, errors = await self._process_plans(tuple(plans), now)
        summary = ScheduledWorkerSummary(created, len(plans), succeeded, len(plans) - succeeded, recovered)
        if errors:
            raise ScheduledDeliveryBatchError(summary, tuple(errors))
        return summary

    async def _process_plans(self, plans, now: dt.datetime) -> tuple[int, list[Exception]]:
        succeeded = 0
        errors: list[Exception] = []
        for plan in plans:
            try:
                outcome = await self._process_one(plan, now)
                if outcome.status is DeliveryStatus.succeeded:
                    succeeded += 1
                else:
                    errors.append(RuntimeError(_outcome_error(plan, outcome)))
            except Exception as exc:
                errors.append(exc)
        return succeeded, errors

    async def _process_one(self, plan, now: dt.datetime) -> DeliveryOutcome:
        await self._dependencies.store.mark_send_started(plan, now)
        try:
            outcome = await self._dependencies.executor.execute(plan)
        except Exception as exc:
            outcome = DeliveryOutcome.uncertain("executor_exception", str(exc))
            await self._finalize(plan, outcome, now)
            raise
        await self._finalize(plan, outcome, now)
        return outcome

    async def _finalize(self, plan, outcome: DeliveryOutcome, now: dt.datetime) -> None:
        try:
            await self._dependencies.store.finalize(plan, outcome, now=now)
        except Exception as exc:
            await self._dependencies.store.mark_finalize_uncertain(plan, exc, now=now)
            raise


def _outcome_error(plan: ScheduledDeliveryPlan, outcome: DeliveryOutcome) -> str:
    detail = outcome.error_code or outcome.message or outcome.status.value
    return f"occurrence={plan.occurrence_id}, status={outcome.status.value}, detail={detail}"
