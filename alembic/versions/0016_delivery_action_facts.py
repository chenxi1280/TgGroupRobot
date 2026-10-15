"""Keep message delivery and ancillary Telegram action results separate."""
from alembic import op

revision = "0016_delivery_action_facts"
down_revision = "0015_general_admin_policies"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS post_actions jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS post_actions jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade():
    raise RuntimeError("Retain delivery action facts; use a forward-compatible application rollback.")
