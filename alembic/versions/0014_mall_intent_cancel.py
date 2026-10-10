"""Persist explicit cancellation without discarding confirmation history."""
from alembic import op
revision = "0014_mall_intent_cancel"
down_revision = "0013_activity_media"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE bot.points_mall_intents ADD COLUMN IF NOT EXISTS cancelled_at timestamptz NULL')


def downgrade():
    raise RuntimeError("Retain cancelled confirmation history; use a forward-compatible application rollback.")
