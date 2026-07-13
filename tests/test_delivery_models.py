from __future__ import annotations

import datetime as dt
import importlib

import pytest


models = importlib.import_module("backend.platform.delivery.models")
retry = importlib.import_module("backend.platform.delivery.retry")


def test_delivery_status_exposes_complete_persisted_contract() -> None:
    status_type = getattr(models, "DeliveryStatus", None)

    assert status_type is not None
    assert {status.value for status in status_type} == {
        "pending",
        "processing",
        "retryable_failed",
        "succeeded",
        "permanent_failed",
        "uncertain",
        "cancelled",
    }


def test_delivery_outcomes_are_immutable_and_typed() -> None:
    outcome_type = getattr(models, "DeliveryOutcome", None)

    assert outcome_type is not None
    success = outcome_type.success(message_id=42, metadata={"source": "verification"})
    retryable = outcome_type.retryable_failure("rate_limited", "retry later")
    permanent = outcome_type.permanent_failure("forbidden", "missing permission")
    uncertain = outcome_type.uncertain("network_timeout", "result unknown")

    assert success.status.value == "succeeded"
    assert success.message_id == 42
    assert success.metadata == (("source", "verification"),)
    assert retryable.status.value == "retryable_failed"
    assert permanent.status.value == "permanent_failed"
    assert uncertain.status.value == "uncertain"
    with pytest.raises(AttributeError):
        success.message_id = 99


def test_retry_policy_uses_bounded_exponential_delay() -> None:
    policy_type = getattr(retry, "RetryPolicy", None)
    calculate = getattr(retry, "calculate_next_retry_at", None)

    assert policy_type is not None
    assert calculate is not None
    now = dt.datetime(2026, 7, 13, tzinfo=dt.UTC)
    policy = policy_type(max_attempts=5, base_delay_seconds=30, max_delay_seconds=120)

    assert calculate(now, attempts=1, policy=policy) == now + dt.timedelta(seconds=30)
    assert calculate(now, attempts=2, policy=policy) == now + dt.timedelta(seconds=60)
    assert calculate(now, attempts=4, policy=policy) == now + dt.timedelta(seconds=120)
    assert calculate(now, attempts=5, policy=policy) is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"base_delay_seconds": 0}, "base_delay_seconds"),
        ({"max_delay_seconds": 0}, "max_delay_seconds"),
    ],
)
def test_retry_policy_rejects_invalid_boundaries(kwargs: dict, message: str) -> None:
    policy_type = getattr(retry, "RetryPolicy", None)

    assert policy_type is not None
    with pytest.raises(ValueError, match=message):
        policy_type(**kwargs)
