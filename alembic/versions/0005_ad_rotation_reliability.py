"""Durable advertisement rotation occurrences."""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0005_ad_rotation_reliability"
down_revision = "0004_scheduled_reliability"
branch_labels = None
depends_on = None

MIGRATION_SQL = Path(__file__).resolve().parents[2] / "sql/migrations/20260713_ad_rotation_reliability.sql"
HISTORY_COLUMNS = (
    "replay_reason", "replay_admin_id", "replay_of_history_id", "error_message",
    "error_code", "completed_at", "send_started_at", "lease_until", "next_retry_at",
    "attempt_count", "status", "rule_snapshot", "content_snapshot", "scheduled_for",
    "dispatch_key",
)


def upgrade() -> None:
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    for statement in sql.replace("BEGIN;", "").replace("COMMIT;", "").split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS bot.ix_ad_rotation_history_due")
    op.execute("DROP INDEX IF EXISTS bot.uq_ad_rotation_history_dispatch_key")
    for column_name in HISTORY_COLUMNS:
        op.execute(f"ALTER TABLE bot.ad_rotation_history DROP COLUMN IF EXISTS {column_name}")
    op.execute("ALTER TABLE bot.ad_rotation_rules DROP COLUMN IF EXISTS exclude_campaign_ids")
    op.execute("ALTER TABLE bot.ad_rotation_rules DROP COLUMN IF EXISTS top_campaign_ids")
