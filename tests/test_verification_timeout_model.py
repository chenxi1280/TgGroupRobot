from __future__ import annotations

from backend.platform.db.runtime.schema_gate import REQUIRED_INDEXES
from backend.platform.db.schema.models import moderation


TIMEOUT_COLUMNS = {
    "timeout_status",
    "timeout_action",
    "timeout_attempts",
    "timeout_next_retry_at",
    "timeout_lease_until",
    "timeout_send_started_at",
    "timeout_last_error",
    "timeout_completed_at",
    "timeout_replay_of_attempt_id",
}

ATTEMPT_COLUMNS = {
    "id",
    "challenge_id",
    "attempt_no",
    "status",
    "action",
    "lease_until",
    "send_started_at",
    "error_code",
    "error_message",
    "completed_at",
    "replay_of_id",
    "created_at",
}


def test_verification_challenge_has_durable_timeout_state_columns() -> None:
    columns = set(moderation.VerificationChallenge.__table__.columns.keys())

    assert TIMEOUT_COLUMNS <= columns
    assert moderation.VerificationChallenge.__table__.columns.timeout_status.nullable is False
    assert moderation.VerificationChallenge.__table__.columns.timeout_attempts.nullable is False


def test_verification_timeout_attempt_preserves_execution_history() -> None:
    attempt_type = getattr(moderation, "VerificationTimeoutAttempt", None)

    assert attempt_type is not None
    assert ATTEMPT_COLUMNS <= set(attempt_type.__table__.columns.keys())
    constraints = {constraint.name for constraint in attempt_type.__table__.constraints}
    assert "uq_verification_timeout_attempt_no" in constraints


def test_schema_gate_requires_timeout_claim_and_attempt_indexes() -> None:
    required = {
        (item.table_name, item.index_name, item.columns, item.unique)
        for item in REQUIRED_INDEXES
    }

    assert (
        "verification_challenges",
        "ix_verification_timeout_due",
        ("timeout_status", "timeout_next_retry_at", "timeout_lease_until"),
        False,
    ) in required
    assert (
        "verification_timeout_attempts",
        "uq_verification_timeout_attempt_no",
        ("challenge_id", "attempt_no"),
        True,
    ) in required
    assert (
        "verification_timeout_attempts",
        "ix_verification_timeout_attempt_status_created",
        ("status", "created_at"),
        False,
    ) in required
