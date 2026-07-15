"""Durable scheduled message occurrences."""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0004_scheduled_reliability"
down_revision = "0003_garage_forward_reliability"
branch_labels = None
depends_on = None

MIGRATION_SQL = Path(__file__).resolve().parents[2] / "sql/migrations/20260713_scheduled_message_occurrences.sql"
DOWNGRADE_COLUMNS = (
    "error_code", "completed_at", "send_started_at", "lease_until",
    "next_retry_at", "attempt_count", "status", "content_snapshot",
    "scheduled_for", "run_key",
)


def upgrade() -> None:
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    for statement in sql.replace("BEGIN;", "").replace("COMMIT;", "").split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS bot.ix_sml_due")
    op.execute("DROP INDEX IF EXISTS bot.uq_sml_run_key")
    for column_name in DOWNGRADE_COLUMNS:
        op.execute(f"ALTER TABLE bot.scheduled_message_logs DROP COLUMN IF EXISTS {column_name}")
