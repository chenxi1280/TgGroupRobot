from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY_SECONDS = 60
DEFAULT_MAX_DELAY_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay_seconds: int = DEFAULT_BASE_DELAY_SECONDS
    max_delay_seconds: int = DEFAULT_MAX_DELAY_SECONDS

    def __post_init__(self) -> None:
        _require_positive("max_attempts", self.max_attempts)
        _require_positive("base_delay_seconds", self.base_delay_seconds)
        _require_positive("max_delay_seconds", self.max_delay_seconds)


def _require_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def calculate_next_retry_at(
    now: dt.datetime,
    *,
    attempts: int,
    policy: RetryPolicy,
) -> dt.datetime | None:
    if attempts >= policy.max_attempts:
        return None
    exponent = max(attempts - 1, 0)
    delay_seconds = min(
        policy.base_delay_seconds * (2**exponent),
        policy.max_delay_seconds,
    )
    return now + dt.timedelta(seconds=delay_seconds)
