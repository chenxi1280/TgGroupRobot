from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select

from backend.platform.db.schema.models.moderation import (
    VerificationChallenge,
    VerificationTimeoutAttempt,
)
from backend.platform.delivery import DeliveryStatus


DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
ACTION_RETRY = "retry"
ACTION_CANCEL = "cancel"
ACTION_REPLAY = "replay_confirm"
RETRYABLE_ADMIN_STATUSES = {
    DeliveryStatus.retryable_failed,
    DeliveryStatus.permanent_failed,
}


@dataclass(frozen=True, slots=True)
class TimeoutTaskFilter:
    chat_id: int
    statuses: tuple[DeliveryStatus, ...]
    limit: int = DEFAULT_LIST_LIMIT

    def __post_init__(self) -> None:
        if not self.statuses:
            raise ValueError("statuses must not be empty")
        if not 1 <= self.limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")


@dataclass(frozen=True, slots=True)
class TimeoutTaskItem:
    id: int
    chat_id: int
    user_id: int
    status: str
    action: str | None
    attempts: int
    last_error: str | None
    completed_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class TimeoutOperation:
    challenge_id: int
    chat_id: int
    action: str
    now: dt.datetime


def build_timeout_task_query(filters: TimeoutTaskFilter):
    return (
        select(VerificationChallenge)
        .where(
            VerificationChallenge.chat_id == filters.chat_id,
            VerificationChallenge.timeout_status.in_(
                tuple(status.value for status in filters.statuses)
            ),
        )
        .order_by(
            VerificationChallenge.timeout_completed_at.desc().nullslast(),
            VerificationChallenge.expires_at.desc(),
        )
        .limit(filters.limit)
    )


def build_timeout_operation_query(*, challenge_id: int, chat_id: int):
    return (
        select(VerificationChallenge)
        .where(
            VerificationChallenge.id == challenge_id,
            VerificationChallenge.chat_id == chat_id,
        )
        .with_for_update()
    )


def serialize_timeout_task(challenge: VerificationChallenge) -> dict:
    return {
        "id": challenge.id,
        "chat_id": int(challenge.chat_id),
        "user_id": int(challenge.user_id),
        "status": challenge.timeout_status,
        "action": challenge.timeout_action,
        "attempts": int(challenge.timeout_attempts or 0),
        "last_error": challenge.timeout_last_error,
        "completed_at": challenge.timeout_completed_at,
    }


async def list_timeout_tasks(
    session,
    filters: TimeoutTaskFilter,
) -> tuple[TimeoutTaskItem, ...]:
    result = await session.execute(build_timeout_task_query(filters))
    return tuple(
        TimeoutTaskItem(**serialize_timeout_task(challenge))
        for challenge in result.scalars().all()
    )


async def apply_timeout_operation(session, operation: TimeoutOperation) -> None:
    result = await session.execute(
        build_timeout_operation_query(
            challenge_id=operation.challenge_id,
            chat_id=operation.chat_id,
        )
    )
    challenge = result.scalar_one_or_none()
    if challenge is None:
        raise ValueError("超时任务不存在或不属于当前群")
    if operation.action == ACTION_RETRY:
        request_timeout_retry(challenge, now=operation.now)
        return
    if operation.action == ACTION_CANCEL:
        cancel_timeout_task(challenge, now=operation.now)
        return
    if operation.action == ACTION_REPLAY:
        attempt = await _load_current_attempt(session, challenge)
        request_uncertain_replay(challenge, attempt, now=operation.now)
        return
    raise ValueError(f"未知超时任务操作: {operation.action}")


def request_timeout_retry(
    challenge: VerificationChallenge,
    *,
    now: dt.datetime,
) -> None:
    status = DeliveryStatus(challenge.timeout_status)
    if status is DeliveryStatus.uncertain:
        raise ValueError("结果不确定任务必须使用确认重放")
    if status not in RETRYABLE_ADMIN_STATUSES:
        raise ValueError(f"当前状态不允许重试: {status.value}")
    _reset_to_pending(challenge, now=now)


def request_uncertain_replay(
    challenge: VerificationChallenge,
    attempt: VerificationTimeoutAttempt,
    *,
    now: dt.datetime,
) -> None:
    if challenge.timeout_status != DeliveryStatus.uncertain.value:
        raise ValueError("只有结果不确定任务可以确认重放")
    if attempt.challenge_id != challenge.id or attempt.status != DeliveryStatus.uncertain.value:
        raise ValueError("重放来源记录与任务不匹配")
    _reset_to_pending(challenge, now=now)
    challenge.timeout_replay_of_attempt_id = attempt.id


def cancel_timeout_task(
    challenge: VerificationChallenge,
    *,
    now: dt.datetime,
) -> None:
    status = DeliveryStatus(challenge.timeout_status)
    if status in {DeliveryStatus.succeeded, DeliveryStatus.cancelled}:
        raise ValueError(f"当前状态不允许关闭: {status.value}")
    challenge.timeout_status = DeliveryStatus.cancelled.value
    challenge.timeout_next_retry_at = None
    challenge.timeout_lease_until = None
    challenge.timeout_completed_at = now
    challenge.timeout_handled = False


def _reset_to_pending(
    challenge: VerificationChallenge,
    *,
    now: dt.datetime,
) -> None:
    challenge.timeout_status = DeliveryStatus.pending.value
    challenge.timeout_next_retry_at = now
    challenge.timeout_lease_until = None
    challenge.timeout_send_started_at = None
    challenge.timeout_last_error = None
    challenge.timeout_completed_at = None
    challenge.timeout_handled = False


async def _load_current_attempt(
    session,
    challenge: VerificationChallenge,
) -> VerificationTimeoutAttempt:
    result = await session.execute(
        select(VerificationTimeoutAttempt)
        .where(
            VerificationTimeoutAttempt.challenge_id == challenge.id,
            VerificationTimeoutAttempt.attempt_no == challenge.timeout_attempts,
        )
        .with_for_update()
    )
    attempt = result.scalar_one_or_none()
    if attempt is None:
        raise ValueError("找不到当前超时执行记录")
    return attempt
