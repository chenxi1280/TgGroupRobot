from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from backend.features.automation.ad_delivery_executor import AdDeliveryExecutor, AdDeliveryPlan
from backend.features.automation.ad_delivery_repository import AdPlanningResult
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus

DEFAULT_BATCH_SIZE = 100
DEFAULT_LEASE_SECONDS = 120


class AdDeliveryStore(Protocol):
    async def create_due_dispatches(self, now: dt.datetime) -> AdPlanningResult: ...
    async def recover_expired_leases(self, now: dt.datetime) -> int: ...
    async def claim_due(self, now: dt.datetime, lease_until: dt.datetime, *, limit: int): ...
    async def mark_send_started(self, plan: AdDeliveryPlan, now: dt.datetime) -> None: ...
    async def finalize(self, plan, outcome: DeliveryOutcome, *, now: dt.datetime) -> None: ...
    async def mark_finalize_uncertain(self, plan, error: Exception, *, now: dt.datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class AdWorkerConfig:
    batch_size: int = DEFAULT_BATCH_SIZE
    lease_seconds: int = DEFAULT_LEASE_SECONDS


@dataclass(frozen=True, slots=True)
class AdWorkerDependencies:
    store: AdDeliveryStore
    executor: AdDeliveryExecutor
    clock: Callable[[], dt.datetime]
    config: AdWorkerConfig = field(default_factory=AdWorkerConfig)


@dataclass(frozen=True, slots=True)
class AdWorkerSummary:
    created: int
    planning_failed: int
    claimed: int
    succeeded: int
    failed: int
    recovered: int


class AdDeliveryBatchError(RuntimeError):
    def __init__(self, summary: AdWorkerSummary, errors: tuple[Exception, ...]) -> None:
        super().__init__(
            f"ad delivery batch failed: planning_failed={summary.planning_failed}, "
            f"claimed={summary.claimed}, failed={summary.failed}"
        )
        self.summary = summary
        self.errors = errors


class AdDeliveryWorker:
    def __init__(self, dependencies: AdWorkerDependencies) -> None:
        self._dependencies = dependencies

    async def run(self) -> AdWorkerSummary:
        now = self._dependencies.clock()
        planning = await self._dependencies.store.create_due_dispatches(now)
        recovered = await self._dependencies.store.recover_expired_leases(now)
        lease_until = now + dt.timedelta(seconds=self._dependencies.config.lease_seconds)
        plans = tuple(await self._dependencies.store.claim_due(
            now,
            lease_until,
            limit=self._dependencies.config.batch_size,
        ))
        succeeded, errors = await self._process_plans(plans, now)
        if planning.failed:
            errors.append(RuntimeError(f"invalid ad rotation pools: {planning.failed}"))
        summary = AdWorkerSummary(
            planning.created,
            planning.failed,
            len(plans),
            succeeded,
            len(plans) - succeeded,
            recovered,
        )
        if errors:
            raise AdDeliveryBatchError(summary, tuple(errors))
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


def _outcome_error(plan: AdDeliveryPlan, outcome: DeliveryOutcome) -> str:
    detail = outcome.error_code or outcome.message or outcome.status.value
    return f"history={plan.history_id}, status={outcome.status.value}, detail={detail}"
