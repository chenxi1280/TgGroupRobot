"""Durable verification timeout execution state."""
from __future__ import annotations

from alembic import op

revision = "0002_verification_reliability"
down_revision = "0001_legacy_baseline"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_status VARCHAR(32) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_action VARCHAR(16)",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_next_retry_at TIMESTAMPTZ",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_lease_until TIMESTAMPTZ",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_send_started_at TIMESTAMPTZ",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_last_error TEXT",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_completed_at TIMESTAMPTZ",
    "ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_replay_of_attempt_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_verification_timeout_due ON bot.verification_challenges(timeout_status, timeout_next_retry_at, timeout_lease_until)",
    """CREATE TABLE IF NOT EXISTS bot.verification_timeout_attempts (
        id SERIAL PRIMARY KEY,
        challenge_id INTEGER NOT NULL REFERENCES bot.verification_challenges(id) ON DELETE CASCADE,
        attempt_no INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL,
        action VARCHAR(16) NOT NULL,
        lease_until TIMESTAMPTZ,
        send_started_at TIMESTAMPTZ,
        error_code VARCHAR(64),
        error_message TEXT,
        completed_at TIMESTAMPTZ,
        replay_of_id INTEGER,
        operator_user_id BIGINT,
        replay_reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_verification_timeout_attempt_no UNIQUE (challenge_id, attempt_no)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_verification_timeout_attempt_status_created ON bot.verification_timeout_attempts(status, created_at)",
)

DOWNGRADE_COLUMNS = (
    "timeout_replay_of_attempt_id", "timeout_completed_at", "timeout_last_error",
    "timeout_send_started_at", "timeout_lease_until", "timeout_next_retry_at",
    "timeout_attempts", "timeout_action", "timeout_status",
)


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bot.verification_timeout_attempts")
    op.execute("DROP INDEX IF EXISTS bot.ix_verification_timeout_due")
    for column_name in DOWNGRADE_COLUMNS:
        op.execute(f"ALTER TABLE bot.verification_challenges DROP COLUMN IF EXISTS {column_name}")
