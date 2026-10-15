"""Explicit auction policy, lottery username checks and typed alliance sanctions."""
from alembic import op

revision = "0015_general_admin_policies"
down_revision = "0014_mall_intent_cancel"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE bot.auction_settings ADD COLUMN IF NOT EXISTS permission_enforced boolean NOT NULL DEFAULT false')
    op.execute('ALTER TABLE bot.lottery_settings ADD COLUMN IF NOT EXISTS require_username boolean NOT NULL DEFAULT false')
    op.execute("ALTER TABLE bot.group_alliance_ban_pool ADD COLUMN IF NOT EXISTS punishment_type varchar(16) NOT NULL DEFAULT 'ban'")


def downgrade():
    raise RuntimeError("Retain explicit permissions and sanction types; use a forward-compatible application rollback.")
