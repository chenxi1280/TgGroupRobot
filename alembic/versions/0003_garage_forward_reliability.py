"""Durable garage forward execution state."""
from __future__ import annotations

from alembic import op

revision = "0003_garage_forward_reliability"
down_revision = "0002_verification_reliability"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS message_map_id INTEGER REFERENCES bot.garage_forward_message_map(id) ON DELETE SET NULL",
    "ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS reply_markup_snapshot JSONB",
    "ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ",
    "ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS send_started_at TIMESTAMPTZ",
    "ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_garage_forward_retry_event ON bot.garage_forward_retry_queue(chat_id, source_channel_id, source_message_id)",
    "CREATE INDEX IF NOT EXISTS ix_garage_forward_retry_due ON bot.garage_forward_retry_queue(status, next_retry_at, lease_until)",
)

DOWNGRADE_COLUMNS = (
    "completed_at", "send_started_at", "lease_until", "status",
    "reply_markup_snapshot", "message_map_id",
)


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS bot.ix_garage_forward_retry_due")
    op.execute("DROP INDEX IF EXISTS bot.uq_garage_forward_retry_event")
    for column_name in DOWNGRADE_COLUMNS:
        op.execute(f"ALTER TABLE bot.garage_forward_retry_queue DROP COLUMN IF EXISTS {column_name}")
