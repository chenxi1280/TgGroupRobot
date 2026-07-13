from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import and_, or_, select

from backend.platform.db.schema.models.moderation import (
    VerificationChallenge,
    VerificationTimeoutAttempt,
)
from backend.platform.delivery import (
    DeliveryOutcome,
    DeliveryStatus,
    RetryPolicy,
    calculate_next_retry_at,
)
from backend.features.verification.timeout_executor import VerificationTimeoutPlan
from backend.features.verification.verification_service import is_self_review_question


DEFAULT_MUTE_DURATION_SECONDS = 86400


@dataclass(frozen=True, slots=True)
class AttemptClaim:
    action: str
    now: dt.datetime
    lease_until: dt.datetime
    replay_of_id: int | None = None


def build_due_query(now: dt.datetime, *, limit: int):
    retry_due = and_(
        VerificationChallenge.timeout_status == DeliveryStatus.retryable_failed.value,
        or_(
            VerificationChallenge.timeout_next_retry_at.is_(None),
            VerificationChallenge.timeout_next_retry_at <= now,
        ),
    )
    return (
        select(VerificationChallenge)
        .where(
            VerificationChallenge.expires_at <= now,
            VerificationChallenge.solved.is_(False),
            or_(
                VerificationChallenge.timeout_status == DeliveryStatus.pending.value,
                retry_due,
            ),
        )
        .order_by(VerificationChallenge.expires_at, VerificationChallenge.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def build_expired_lease_query(now: dt.datetime, *, limit: int):
    return (
        select(VerificationChallenge)
        .where(
            VerificationChallenge.timeout_status == DeliveryStatus.processing.value,
            VerificationChallenge.timeout_lease_until <= now,
        )
        .order_by(VerificationChallenge.timeout_lease_until, VerificationChallenge.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def build_processing_challenge_query(challenge_id: int):
    return (
        select(VerificationChallenge)
        .where(
            VerificationChallenge.id == challenge_id,
            VerificationChallenge.timeout_status == DeliveryStatus.processing.value,
        )
        .with_for_update()
    )


def build_attempt_query(attempt_id: int):
    return (
        select(VerificationTimeoutAttempt)
        .where(VerificationTimeoutAttempt.id == attempt_id)
        .with_for_update()
    )


def resolve_timeout_action(challenge, settings) -> tuple[str, int]:
    if challenge.verification_type == "admin":
        return "none", 0
    duration = int(
        getattr(settings, "verification_mute_duration", DEFAULT_MUTE_DURATION_SECONDS)
        or DEFAULT_MUTE_DURATION_SECONDS
    )
    if is_self_review_question(challenge.question):
        action = getattr(settings, "join_self_review_timeout_action", "mute")
        return ("kick" if action == "reject_block" else "mute"), duration
    configured = getattr(settings, "verification_timeout_action", "mute")
    if configured == "none":
        return "unrestrict", duration
    if configured == "kick":
        return "kick", duration
    return "mute", duration


def create_attempt(
    session,
    challenge: VerificationChallenge,
    claim: AttemptClaim,
) -> VerificationTimeoutAttempt:
    attempt_no = int(challenge.timeout_attempts or 0) + 1
    attempt = VerificationTimeoutAttempt(
        challenge_id=challenge.id,
        attempt_no=attempt_no,
        status=DeliveryStatus.processing.value,
        action=claim.action,
        lease_until=claim.lease_until,
        replay_of_id=claim.replay_of_id or challenge.timeout_replay_of_attempt_id,
        created_at=claim.now,
    )
    challenge.timeout_status = DeliveryStatus.processing.value
    challenge.timeout_action = claim.action
    challenge.timeout_attempts = attempt_no
    challenge.timeout_next_retry_at = None
    challenge.timeout_lease_until = claim.lease_until
    challenge.timeout_send_started_at = None
    challenge.timeout_last_error = None
    challenge.timeout_completed_at = None
    challenge.timeout_replay_of_attempt_id = None
    session.add(attempt)
    return attempt


def mark_send_started(
    challenge: VerificationChallenge,
    attempt: VerificationTimeoutAttempt,
    now: dt.datetime,
) -> None:
    challenge.timeout_send_started_at = now
    attempt.send_started_at = now


def finalize_attempt(
    challenge: VerificationChallenge,
    attempt: VerificationTimeoutAttempt,
    outcome: DeliveryOutcome,
    *,
    now: dt.datetime,
    retry_policy: RetryPolicy,
) -> None:
    status, next_retry_at = _resolve_status(
        challenge,
        outcome,
        now=now,
        policy=retry_policy,
    )
    challenge.timeout_status = status.value
    challenge.timeout_next_retry_at = next_retry_at
    challenge.timeout_lease_until = None
    challenge.timeout_last_error = _format_error(outcome)
    challenge.timeout_completed_at = now if _is_terminal(status) else None
    challenge.timeout_handled = status is DeliveryStatus.succeeded
    if status is DeliveryStatus.succeeded and challenge.timeout_action == "unrestrict":
        challenge.solved = True
    _finalize_attempt_record(
        attempt,
        outcome,
        status=status,
        now=now,
    )


def recover_expired_attempt(
    challenge: VerificationChallenge,
    attempt: VerificationTimeoutAttempt,
    now: dt.datetime,
) -> None:
    started = bool(challenge.timeout_send_started_at or attempt.send_started_at)
    status = DeliveryStatus.uncertain if started else DeliveryStatus.retryable_failed
    challenge.timeout_status = status.value
    challenge.timeout_next_retry_at = None if started else now
    challenge.timeout_lease_until = None
    challenge.timeout_last_error = "lease_expired_after_send" if started else "lease_expired_before_send"
    challenge.timeout_completed_at = now if started else None
    challenge.timeout_handled = False
    attempt.status = status.value
    attempt.error_code = challenge.timeout_last_error
    attempt.error_message = challenge.timeout_last_error
    attempt.completed_at = now
    attempt.lease_until = None


def _resolve_status(
    challenge: VerificationChallenge,
    outcome: DeliveryOutcome,
    *,
    now: dt.datetime,
    policy: RetryPolicy,
) -> tuple[DeliveryStatus, dt.datetime | None]:
    if outcome.status is not DeliveryStatus.retryable_failed:
        return outcome.status, None
    next_retry = calculate_next_retry_at(
        now,
        attempts=challenge.timeout_attempts,
        policy=policy,
    )
    if next_retry is None:
        return DeliveryStatus.permanent_failed, None
    return DeliveryStatus.retryable_failed, next_retry


def _finalize_attempt_record(
    attempt: VerificationTimeoutAttempt,
    outcome: DeliveryOutcome,
    *,
    status: DeliveryStatus,
    now: dt.datetime,
) -> None:
    attempt.status = status.value
    attempt.error_code = outcome.error_code
    attempt.error_message = outcome.message
    attempt.completed_at = now
    attempt.lease_until = None


def _format_error(outcome: DeliveryOutcome) -> str | None:
    if not outcome.error_code:
        return outcome.message
    if not outcome.message:
        return outcome.error_code
    return f"{outcome.error_code}: {outcome.message}"


def _is_terminal(status: DeliveryStatus) -> bool:
    return status in {
        DeliveryStatus.succeeded,
        DeliveryStatus.permanent_failed,
        DeliveryStatus.uncertain,
        DeliveryStatus.cancelled,
    }


class SqlAlchemyVerificationTimeoutStore:
    def __init__(self, db, settings_loader, *, retry_policy: RetryPolicy | None = None) -> None:
        self._db = db
        self._settings_loader = settings_loader
        self._retry_policy = retry_policy or RetryPolicy()

    async def recover_expired_leases(self, now: dt.datetime) -> int:
        async with self._db.session_factory() as session:
            result = await session.execute(build_expired_lease_query(now, limit=DEFAULT_BATCH_LIMIT))
            challenges = tuple(result.scalars().all())
            for challenge in challenges:
                attempt = await _load_current_attempt(session, challenge)
                recover_expired_attempt(challenge, attempt, now)
            await session.commit()
        return len(challenges)

    async def claim_due(
        self,
        now: dt.datetime,
        lease_until: dt.datetime,
        *,
        limit: int,
    ) -> tuple[VerificationTimeoutPlan, ...]:
        async with self._db.session_factory() as session:
            result = await session.execute(build_due_query(now, limit=limit))
            challenges = tuple(result.scalars().all())
            plans = await self._claim_challenges(
                session,
                challenges=challenges,
                now=now,
                lease_until=lease_until,
            )
            await session.commit()
        return tuple(plans)

    async def mark_send_started(
        self,
        plan: VerificationTimeoutPlan,
        now: dt.datetime,
    ) -> None:
        async with self._db.session_factory() as session:
            challenge, attempt = await _load_plan_entities(session, plan)
            mark_send_started(challenge, attempt, now)
            await session.commit()

    async def finalize(
        self,
        plan: VerificationTimeoutPlan,
        outcome: DeliveryOutcome,
        *,
        now: dt.datetime,
    ) -> None:
        async with self._db.session_factory() as session:
            challenge, attempt = await _load_plan_entities(session, plan)
            finalize_attempt(
                challenge,
                attempt,
                outcome,
                now=now,
                retry_policy=self._retry_policy,
            )
            await session.commit()

    async def _claim_challenges(
        self,
        session,
        *,
        challenges: tuple[VerificationChallenge, ...],
        now: dt.datetime,
        lease_until: dt.datetime,
    ) -> list[VerificationTimeoutPlan]:
        plans: list[VerificationTimeoutPlan] = []
        for challenge in challenges:
            settings = await self._settings_loader(session, challenge.chat_id)
            action, duration = resolve_timeout_action(challenge, settings)
            attempt = create_attempt(
                session,
                challenge,
                AttemptClaim(action=action, now=now, lease_until=lease_until),
            )
            await session.flush()
            plans.append(
                _build_plan(
                    challenge,
                    attempt,
                    action=action,
                    duration=duration,
                )
            )
        return plans


DEFAULT_BATCH_LIMIT = 50


def _build_plan(
    challenge: VerificationChallenge,
    attempt: VerificationTimeoutAttempt,
    *,
    action: str,
    duration: int,
) -> VerificationTimeoutPlan:
    return VerificationTimeoutPlan(
        challenge_id=challenge.id,
        attempt_id=attempt.id,
        chat_id=int(challenge.chat_id),
        user_id=int(challenge.user_id),
        action=action,
        duration_seconds=duration,
    )


async def _load_current_attempt(session, challenge) -> VerificationTimeoutAttempt:
    result = await session.execute(
        select(VerificationTimeoutAttempt).where(
            VerificationTimeoutAttempt.challenge_id == challenge.id,
            VerificationTimeoutAttempt.attempt_no == challenge.timeout_attempts,
        )
    )
    attempt = result.scalar_one_or_none()
    if attempt is None:
        raise RuntimeError(f"missing timeout attempt for challenge {challenge.id}")
    return attempt


async def _load_plan_entities(session, plan: VerificationTimeoutPlan):
    challenge_result = await session.execute(
        build_processing_challenge_query(plan.challenge_id)
    )
    attempt_result = await session.execute(build_attempt_query(plan.attempt_id))
    challenge = challenge_result.scalar_one_or_none()
    attempt = attempt_result.scalar_one_or_none()
    if challenge is None or attempt is None:
        raise RuntimeError(
            f"missing timeout entities: challenge={plan.challenge_id}, attempt={plan.attempt_id}"
        )
    if attempt.status != DeliveryStatus.processing.value:
        raise RuntimeError(f"timeout attempt is not processing: {plan.attempt_id}")
    return challenge, attempt
