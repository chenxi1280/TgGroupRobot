from __future__ import annotations

from sqlalchemy import UniqueConstraint

from backend.platform.db.schema.models.alliance import GarageForwardRetryQueue


def test_garage_retry_queue_has_durable_delivery_fields() -> None:
    columns = GarageForwardRetryQueue.__table__.columns

    assert {
        "message_map_id",
        "reply_markup_snapshot",
        "status",
        "lease_until",
        "send_started_at",
        "last_error",
        "completed_at",
    }.issubset(columns.keys())
    assert columns["status"].default.arg == "pending"


def test_garage_retry_queue_is_unique_per_source_event() -> None:
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in GarageForwardRetryQueue.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("chat_id", "source_channel_id", "source_message_id") in unique_columns
