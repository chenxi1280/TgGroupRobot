from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from backend.features.garage.forward_delivery_admin_service import (
    GarageTaskFilter,
    build_garage_task_query,
    cancel_garage_delivery,
    request_garage_replay,
    request_garage_retry,
)
from backend.platform.delivery import DeliveryStatus


NOW = dt.datetime(2026, 7, 13, 13, tzinfo=dt.UTC)


def _delivery(status: DeliveryStatus):
    return SimpleNamespace(
        id=7,
        chat_id=-20001,
        source_channel_id=-10001,
        source_message_id=321,
        status=status.value,
        retry_count=3,
        next_retry_at=None,
        lease_until=None,
        send_started_at=NOW,
        last_error="failure",
        completed_at=NOW,
    )


def test_admin_list_query_is_chat_scoped_and_status_filtered() -> None:
    query = build_garage_task_query(GarageTaskFilter(
        chat_id=-20001,
        statuses=(DeliveryStatus.permanent_failed, DeliveryStatus.uncertain),
    ))
    sql = str(query.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))

    assert "chat_id = -20001" in sql
    assert "permanent_failed" in sql
    assert "uncertain" in sql


def test_regular_retry_rejects_uncertain_and_resets_permanent_failure() -> None:
    uncertain = _delivery(DeliveryStatus.uncertain)
    with pytest.raises(ValueError, match="不确定"):
        request_garage_retry(uncertain, now=NOW)

    delivery = _delivery(DeliveryStatus.permanent_failed)
    request_garage_retry(delivery, now=NOW)
    assert delivery.status == "pending"
    assert delivery.next_retry_at == NOW
    assert delivery.send_started_at is None


def test_uncertain_replay_requires_confirmation_and_resets_attempts() -> None:
    delivery = _delivery(DeliveryStatus.uncertain)

    with pytest.raises(ValueError, match="确认"):
        request_garage_replay(delivery, now=NOW, confirmed=False)

    request_garage_replay(delivery, now=NOW, confirmed=True)
    assert delivery.status == "pending"
    assert delivery.retry_count == 0
    assert delivery.next_retry_at == NOW


def test_cancel_is_terminal_and_cannot_cancel_succeeded() -> None:
    delivery = _delivery(DeliveryStatus.retryable_failed)
    cancel_garage_delivery(delivery, now=NOW)
    assert delivery.status == "cancelled"
    assert delivery.completed_at == NOW

    with pytest.raises(ValueError, match="不允许"):
        cancel_garage_delivery(_delivery(DeliveryStatus.succeeded), now=NOW)
