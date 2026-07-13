from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from backend.features.verification.timeout_executor import (
    ACTION_NONE,
    VerificationTimeoutExecutor,
    VerificationTimeoutPlan,
)
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus


DEFAULT_BATCH_SIZE = 50
DEFAULT_LEASE_SECONDS = 120


class VerificationTimeoutStore(Protocol):
    async def recover_expired_leases(self, now: dt.datetime) -> int: ...

    async def claim_due(
        self,
        now: dt.datetime,
        lease_until: dt.datetime,
        *,
        limit: int,
    ) -> tuple[VerificationTimeoutPlan, ...]: ...

    async def mark_send_started(
        self,
        plan: VerificationTimeoutPlan,
        now: dt.datetime,
    ) -> None: ...

    async def finalize(
        self,
        plan: VerificationTimeoutPlan,
        outcome: DeliveryOutcome,
        *,
        now: dt.datetime,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    batch_size: int = DEFAULT_BATCH_SIZE
    lease_seconds: int = DEFAULT_LEASE_SECONDS


@dataclass(frozen=True, slots=True)
class WorkerDependencies:
    store: VerificationTimeoutStore
    executor: VerificationTimeoutExecutor
    clock: Callable[[], dt.datetime]
    config: WorkerConfig = field(default_factory=WorkerConfig)


@dataclass(frozen=True, slots=True)
class WorkerSummary:
    claimed: int
    succeeded: int
    failed: int
    recovered: int


class VerificationTimeoutBatchError(RuntimeError):
    def __init__(self, summary: WorkerSummary, errors: tuple[Exception, ...]) -> None:
        super().__init__(
            "verification timeout batch failed: "
            f"claimed={summary.claimed}, failed={summary.failed}, errors={len(errors)}"
        )
        self.summary = summary
        self.errors = errors


class VerificationTimeoutWorker:
    def __init__(self, dependencies: WorkerDependencies) -> None:
        self._dependencies = dependencies

    async def run(self) -> WorkerSummary:
        now = self._dependencies.clock()
        recovered = await self._dependencies.store.recover_expired_leases(now)
        lease_until = now + dt.timedelta(seconds=self._dependencies.config.lease_seconds)
        plans = await self._dependencies.store.claim_due(
            now,
            lease_until,
            limit=self._dependencies.config.batch_size,
        )
        succeeded, errors = await self._process_plans(plans, now)
        summary = WorkerSummary(
            claimed=len(plans),
            succeeded=succeeded,
            failed=len(plans) - succeeded,
            recovered=recovered,
        )
        if errors:
            raise VerificationTimeoutBatchError(summary, tuple(errors))
        return summary

    async def _process_plans(
        self,
        plans: tuple[VerificationTimeoutPlan, ...],
        now: dt.datetime,
    ) -> tuple[int, list[Exception]]:
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

    async def _process_one(
        self,
        plan: VerificationTimeoutPlan,
        now: dt.datetime,
    ) -> DeliveryOutcome:
        if plan.action != ACTION_NONE:
            await self._dependencies.store.mark_send_started(plan, now)
        try:
            outcome = await self._dependencies.executor.execute(plan)
        except Exception as exc:
            outcome = DeliveryOutcome.uncertain("executor_exception", str(exc))
            await self._dependencies.store.finalize(plan, outcome, now=now)
            raise
        await self._dependencies.store.finalize(plan, outcome, now=now)
        return outcome


def _outcome_error(
    plan: VerificationTimeoutPlan,
    outcome: DeliveryOutcome,
) -> str:
    detail = outcome.error_code or outcome.message or outcome.status.value
    return f"attempt={plan.attempt_id}, status={outcome.status.value}, detail={detail}"
