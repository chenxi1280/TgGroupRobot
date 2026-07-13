from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from backend.features.garage.forward_delivery_repository import (
    GarageDeliveryRequest,
    GarageForwardDeliveryRepository,
    build_due_query,
    build_expired_lease_query,
    finalize_delivery,
    recover_expired_delivery,
)
from backend.platform.delivery import DeliveryOutcome, RetryPolicy


NOW = dt.datetime(2026, 7, 13, 12, tzinfo=dt.UTC)


def _request() -> GarageDeliveryRequest:
    return GarageDeliveryRequest(
        chat_id=-20001,
        source_channel_id=-10001,
        source_message_id=321,
        message_map_id=77,
        reply_markup_snapshot={
            "inline_keyboard": [[{"text": "详情", "url": "https://example.com"}]],
        },
    )


def test_enqueue_statement_upserts_one_record_per_source_event() -> None:
    statement = GarageForwardDeliveryRepository.build_enqueue_statement(_request())
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (chat_id, source_channel_id, source_message_id) DO UPDATE" in sql
    assert "message_map_id" in sql
    assert "reply_markup_snapshot" in sql


def test_enqueue_statement_restores_retryable_record_to_pending() -> None:
    statement = GarageForwardDeliveryRepository.build_enqueue_statement(_request())
    params = statement.compile(dialect=postgresql.dialect()).params

    assert "pending" in params.values()
    assert _request().reply_markup_snapshot in params.values()


def test_due_and_expired_queries_use_locked_claiming() -> None:
    due_sql = str(build_due_query(NOW, limit=25))
    expired_sql = str(build_expired_lease_query(NOW, limit=25))

    assert "FOR UPDATE" in due_sql
    assert "status" in due_sql
    assert "next_retry_at" in due_sql
    assert "FOR UPDATE" in expired_sql
    assert "lease_until" in expired_sql


def test_expired_send_started_delivery_becomes_uncertain() -> None:
    delivery = SimpleNamespace(
        send_started_at=NOW - dt.timedelta(seconds=10),
        status="processing",
        next_retry_at=None,
        lease_until=NOW,
        last_error=None,
        completed_at=None,
    )

    recover_expired_delivery(delivery, NOW)

    assert delivery.status == "uncertain"
    assert delivery.next_retry_at is None
    assert delivery.completed_at == NOW


def test_expired_delivery_before_send_becomes_retryable() -> None:
    delivery = SimpleNamespace(
        send_started_at=None,
        status="processing",
        next_retry_at=None,
        lease_until=NOW,
        last_error=None,
        completed_at=None,
    )

    recover_expired_delivery(delivery, NOW)

    assert delivery.status == "retryable_failed"
    assert delivery.next_retry_at == NOW
    assert delivery.completed_at is None


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item) -> None:
        self.added.append(item)


def test_success_finalization_updates_map_cursor_audit_and_execution() -> None:
    delivery = SimpleNamespace(
        chat_id=-20001,
        source_channel_id=-10001,
        source_message_id=321,
        retry_count=1,
        max_retries=3,
    )
    message_map = SimpleNamespace(target_message_id=0, forwarded_at=None)
    source = SimpleNamespace(last_seen_message_id=300)
    session = FakeSession()

    finalize_delivery(
        session,
        delivery=delivery,
        message_map=message_map,
        source=source,
        outcome=DeliveryOutcome.success(999),
        now=NOW,
        retry_policy=RetryPolicy(),
    )

    assert delivery.status == "succeeded"
    assert delivery.completed_at == NOW
    assert message_map.target_message_id == 999
    assert source.last_seen_message_id == 321
    assert session.added[0].result == "success"
