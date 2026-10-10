"""Keep activity image format for consistent publication and later updates."""
from alembic import op
revision = "0013_activity_media"
down_revision = "0012_ui_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE bot.auction_items ADD COLUMN IF NOT EXISTS cover_file_id varchar(256) NULL')
    op.execute('ALTER TABLE bot.guess_events ADD COLUMN IF NOT EXISTS cover_media_type varchar(16) NULL')


def downgrade():
    raise RuntimeError("Preserve activity media metadata during rollback.")
