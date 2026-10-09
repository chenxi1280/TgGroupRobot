"""Add module_config, ops audit, scheduler state, verification prompt delivery."""
from __future__ import annotations

from alembic import op

revision = "0007_ops_module_config_prompt"
down_revision = "0006_schema_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot.chat_settings
        ADD COLUMN IF NOT EXISTS module_config jsonb NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE bot.verification_challenges
        ADD COLUMN IF NOT EXISTS prompt_status varchar(32) NOT NULL DEFAULT 'pending',
        ADD COLUMN IF NOT EXISTS prompt_message_id integer NULL,
        ADD COLUMN IF NOT EXISTS prompt_attempts integer NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS prompt_last_error text NULL,
        ADD COLUMN IF NOT EXISTS prompt_completed_at timestamptz NULL
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bot.ops_audit_events (
            id serial PRIMARY KEY,
            domain varchar(64) NOT NULL,
            event_type varchar(64) NOT NULL,
            chat_id bigint NULL,
            user_id bigint NULL,
            entity_type varchar(64) NULL,
            entity_id varchar(128) NULL,
            severity varchar(16) NOT NULL DEFAULT 'info',
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ops_audit_events_domain ON bot.ops_audit_events (domain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ops_audit_events_event_type ON bot.ops_audit_events (event_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ops_audit_events_chat_id ON bot.ops_audit_events (chat_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ops_audit_events_entity_id ON bot.ops_audit_events (entity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ops_audit_events_created_at ON bot.ops_audit_events (created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bot.scheduler_task_states (
            task_name varchar(64) PRIMARY KEY,
            enabled boolean NOT NULL DEFAULT true,
            auto_paused boolean NOT NULL DEFAULT false,
            paused_reason text NULL,
            consecutive_errors integer NOT NULL DEFAULT 0,
            total_runs integer NOT NULL DEFAULT 0,
            total_errors integer NOT NULL DEFAULT 0,
            last_success_at timestamptz NULL,
            last_failure_at timestamptz NULL,
            last_error text NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bot.scheduler_task_states")
    op.execute("DROP TABLE IF EXISTS bot.ops_audit_events")
    op.execute(
        """
        ALTER TABLE bot.verification_challenges
        DROP COLUMN IF EXISTS prompt_status,
        DROP COLUMN IF EXISTS prompt_message_id,
        DROP COLUMN IF EXISTS prompt_attempts,
        DROP COLUMN IF EXISTS prompt_last_error,
        DROP COLUMN IF EXISTS prompt_completed_at
        """
    )
    op.execute("ALTER TABLE bot.chat_settings DROP COLUMN IF EXISTS module_config")
