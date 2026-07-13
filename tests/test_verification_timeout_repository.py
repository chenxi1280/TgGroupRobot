from __future__ import annotations

import datetime as dt
import importlib

from sqlalchemy.dialects import postgresql

from backend.platform.db.schema.models.moderation import VerificationChallenge
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus, RetryPolicy


repository = importlib.import_module("backend.features.verification.timeout_repository")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, entity: object) -> None:
        self.added.append(entity)


def _challenge() -> VerificationChallenge:
    challenge = VerificationChallenge(
        chat_id=-100123,
        user_id=99,
        token="token",
        expires_at=dt.datetime(2026, 7, 13, tzinfo=dt.UTC),
        solved=False,
        timeout_handled=False,
        timeout_status=DeliveryStatus.pending.value,
        timeout_attempts=0,
    )
    challenge.id = 7
    return challenge


def test_due_query_uses_locked_due_status_filter() -> None:
    build_query = getattr(repository, "build_due_query", None)

    assert build_query is not None
    query = build_query(dt.datetime(2026, 7, 14, tzinfo=dt.UTC), limit=20)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "pending" in sql
    assert "retryable_failed" in sql
    assert "timeout_next_retry_at" in sql


def test_create_attempt_snapshots_action_and_claims_lease() -> None:
    claim_type = getattr(repository, "AttemptClaim", None)
    create_attempt = getattr(repository, "create_attempt", None)

    assert claim_type is not None
    assert create_attempt is not None
    challenge = _challenge()
    session = FakeSession()
    now = dt.datetime(2026, 7, 14, tzinfo=dt.UTC)
    lease_until = now + dt.timedelta(minutes=2)

    attempt = create_attempt(
        session,
        challenge,
        claim_type(action="mute", now=now, lease_until=lease_until),
    )

    assert challenge.timeout_status == DeliveryStatus.processing.value
    assert challenge.timeout_action == "mute"
    assert challenge.timeout_attempts == 1
    assert challenge.timeout_lease_until == lease_until
    assert attempt.attempt_no == 1
    assert attempt.action == "mute"
    assert session.added == [attempt]


def test_finalize_success_sets_compatibility_fields() -> None:
    claim_type = getattr(repository, "AttemptClaim", None)
    create_attempt = getattr(repository, "create_attempt", None)
    finalize = getattr(repository, "finalize_attempt", None)

    assert claim_type is not None
    assert create_attempt is not None
    assert finalize is not None
    challenge = _challenge()
    now = dt.datetime(2026, 7, 14, tzinfo=dt.UTC)
    attempt = create_attempt(
        FakeSession(),
        challenge,
        claim_type(action="unrestrict", now=now, lease_until=now),
    )

    finalize(
        challenge,
        attempt,
        DeliveryOutcome.success(),
        now=now,
        retry_policy=RetryPolicy(),
    )

    assert challenge.timeout_status == DeliveryStatus.succeeded.value
    assert challenge.timeout_handled is True
    assert challenge.solved is True
    assert challenge.timeout_completed_at == now
    assert attempt.status == DeliveryStatus.succeeded.value


def test_finalize_retryable_failure_schedules_retry() -> None:
    claim_type = getattr(repository, "AttemptClaim", None)
    create_attempt = getattr(repository, "create_attempt", None)
    finalize = getattr(repository, "finalize_attempt", None)

    assert claim_type is not None
    assert create_attempt is not None
    assert finalize is not None
    challenge = _challenge()
    now = dt.datetime(2026, 7, 14, tzinfo=dt.UTC)
    attempt = create_attempt(
        FakeSession(),
        challenge,
        claim_type(action="mute", now=now, lease_until=now),
    )

    finalize(
        challenge,
        attempt,
        DeliveryOutcome.retryable_failure("rate_limited", "retry later"),
        now=now,
        retry_policy=RetryPolicy(base_delay_seconds=30),
    )

    assert challenge.timeout_status == DeliveryStatus.retryable_failed.value
    assert challenge.timeout_handled is False
    assert challenge.timeout_next_retry_at == now + dt.timedelta(seconds=30)
    assert "rate_limited" in challenge.timeout_last_error


def test_expired_started_lease_becomes_uncertain_without_retry() -> None:
    recover = getattr(repository, "recover_expired_attempt", None)

    assert recover is not None
    challenge = _challenge()
    challenge.timeout_status = DeliveryStatus.processing.value
    challenge.timeout_send_started_at = dt.datetime(2026, 7, 14, tzinfo=dt.UTC)
    attempt = type("Attempt", (), {})()
    attempt.send_started_at = challenge.timeout_send_started_at
    now = dt.datetime(2026, 7, 14, 1, tzinfo=dt.UTC)

    recover(challenge, attempt, now)

    assert challenge.timeout_status == DeliveryStatus.uncertain.value
    assert challenge.timeout_next_retry_at is None
    assert challenge.timeout_handled is False
    assert attempt.status == DeliveryStatus.uncertain.value


def test_expired_lease_query_is_locked_and_scoped_to_processing() -> None:
    build_query = getattr(repository, "build_expired_lease_query", None)

    assert build_query is not None
    query = build_query(dt.datetime(2026, 7, 14, tzinfo=dt.UTC), limit=20)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "processing" in sql
    assert "timeout_lease_until" in sql


def test_timeout_action_resolution_persists_effective_business_action() -> None:
    resolve = getattr(repository, "resolve_timeout_action", None)

    assert resolve is not None
    admin = type("Challenge", (), {"verification_type": "admin", "question": None})()
    regular = type("Challenge", (), {"verification_type": "math", "question": "1 + 1 = ?"})()
    settings = type(
        "Settings",
        (),
        {
            "verification_timeout_action": "none",
            "verification_mute_duration": 3600,
            "join_self_review_timeout_action": "reject_block",
        },
    )()

    assert resolve(admin, settings) == ("none", 0)
    assert resolve(regular, settings) == ("unrestrict", 3600)


def test_sqlalchemy_timeout_store_interface_exists() -> None:
    store_type = getattr(repository, "SqlAlchemyVerificationTimeoutStore", None)

    assert store_type is not None
    for method_name in (
        "recover_expired_leases",
        "claim_due",
        "mark_send_started",
        "finalize",
    ):
        assert callable(getattr(store_type, method_name, None))


def test_plan_entity_queries_lock_challenge_and_attempt() -> None:
    challenge_query = getattr(repository, "build_processing_challenge_query", None)
    attempt_query = getattr(repository, "build_attempt_query", None)

    assert challenge_query is not None
    assert attempt_query is not None
    dialect = postgresql.dialect()
    challenge_sql = str(
        challenge_query(7).compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    )
    attempt_sql = str(
        attempt_query(11).compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    )

    assert "FOR UPDATE" in challenge_sql
    assert "processing" in challenge_sql
    assert "FOR UPDATE" in attempt_sql


def test_retry_exhaustion_becomes_permanent_without_compatibility_success() -> None:
    challenge = _challenge()
    challenge.timeout_attempts = 5
    attempt = type("Attempt", (), {})()
    now = dt.datetime(2026, 7, 14, tzinfo=dt.UTC)

    repository.finalize_attempt(
        challenge,
        attempt,
        DeliveryOutcome.retryable_failure("rate_limited", "retry later"),
        now=now,
        retry_policy=RetryPolicy(max_attempts=5),
    )

    assert challenge.timeout_status == DeliveryStatus.permanent_failed.value
    assert challenge.timeout_handled is False
    assert challenge.timeout_completed_at == now
