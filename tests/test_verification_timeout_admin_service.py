from __future__ import annotations

import datetime as dt
import importlib

import pytest
from sqlalchemy.dialects import postgresql

from backend.platform.db.schema.models.moderation import (
    VerificationChallenge,
    VerificationTimeoutAttempt,
)
from backend.platform.delivery import DeliveryStatus


service = importlib.import_module("backend.features.verification.timeout_admin_service")
NOW = dt.datetime(2026, 7, 14, tzinfo=dt.UTC)


def _challenge(status: DeliveryStatus) -> VerificationChallenge:
    challenge = VerificationChallenge(
        chat_id=-100123,
        user_id=99,
        token="token",
        expires_at=NOW,
        solved=False,
        timeout_handled=False,
        timeout_status=status.value,
        timeout_attempts=2,
    )
    challenge.id = 7
    return challenge


def _attempt(status: DeliveryStatus) -> VerificationTimeoutAttempt:
    attempt = VerificationTimeoutAttempt(
        challenge_id=7,
        attempt_no=2,
        status=status.value,
        action="mute",
        created_at=NOW,
    )
    attempt.id = 11
    return attempt


def test_failure_query_is_chat_scoped_and_status_filtered() -> None:
    filter_type = getattr(service, "TimeoutTaskFilter", None)
    build_query = getattr(service, "build_timeout_task_query", None)

    assert filter_type is not None
    assert build_query is not None
    filters = filter_type(
        chat_id=-100123,
        statuses=(DeliveryStatus.permanent_failed, DeliveryStatus.uncertain),
        limit=20,
    )
    sql = str(
        build_query(filters).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "chat_id = -100123" in sql
    assert "permanent_failed" in sql
    assert "uncertain" in sql
    assert "ORDER BY" in sql


def test_explicit_retry_resets_safe_failure_to_pending() -> None:
    request_retry = getattr(service, "request_timeout_retry", None)

    assert request_retry is not None
    challenge = _challenge(DeliveryStatus.permanent_failed)
    request_retry(challenge, now=NOW)

    assert challenge.timeout_status == DeliveryStatus.pending.value
    assert challenge.timeout_next_retry_at == NOW
    assert challenge.timeout_handled is False
    assert challenge.timeout_completed_at is None


def test_uncertain_task_cannot_use_regular_retry() -> None:
    request_retry = getattr(service, "request_timeout_retry", None)

    assert request_retry is not None
    challenge = _challenge(DeliveryStatus.uncertain)

    with pytest.raises(ValueError, match="不确定"):
        request_retry(challenge, now=NOW)


def test_confirmed_uncertain_replay_preserves_attempt_lineage() -> None:
    replay = getattr(service, "request_uncertain_replay", None)

    assert replay is not None
    challenge = _challenge(DeliveryStatus.uncertain)
    attempt = _attempt(DeliveryStatus.uncertain)
    replay(challenge, attempt, now=NOW)

    assert challenge.timeout_status == DeliveryStatus.pending.value
    assert challenge.timeout_replay_of_attempt_id == 11
    assert challenge.timeout_next_retry_at == NOW
    assert challenge.timeout_send_started_at is None


def test_cancel_marks_task_terminal_without_claiming_success() -> None:
    cancel = getattr(service, "cancel_timeout_task", None)

    assert cancel is not None
    challenge = _challenge(DeliveryStatus.retryable_failed)
    cancel(challenge, now=NOW)

    assert challenge.timeout_status == DeliveryStatus.cancelled.value
    assert challenge.timeout_completed_at == NOW
    assert challenge.timeout_handled is False


def test_operation_lock_query_is_chat_scoped_and_for_update() -> None:
    build_query = getattr(service, "build_timeout_operation_query", None)

    assert build_query is not None
    sql = str(
        build_query(challenge_id=7, chat_id=-100123).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "id = 7" in sql
    assert "chat_id = -100123" in sql
    assert "FOR UPDATE" in sql


def test_timeout_task_serialization_exposes_operator_fields() -> None:
    serialize = getattr(service, "serialize_timeout_task", None)

    assert serialize is not None
    challenge = _challenge(DeliveryStatus.permanent_failed)
    challenge.timeout_action = "kick"
    challenge.timeout_last_error = "telegram_forbidden"
    payload = serialize(challenge)

    assert payload["id"] == 7
    assert payload["user_id"] == 99
    assert payload["status"] == "permanent_failed"
    assert payload["action"] == "kick"
    assert payload["attempts"] == 2
    assert payload["last_error"] == "telegram_forbidden"
