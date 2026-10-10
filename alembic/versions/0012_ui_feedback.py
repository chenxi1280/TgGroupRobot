"""Persist rendered operation results when Telegram UI is unreachable."""
from alembic import op
revision = "0012_ui_feedback"
down_revision = "0011_mall_fulfillment"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE IF NOT EXISTS bot.ui_feedback (
        token varchar(32) PRIMARY KEY, user_id bigint NOT NULL,
        text text NOT NULL, status varchar(16) NOT NULL, created_at timestamptz NOT NULL
    )''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_ui_feedback_user_id ON bot.ui_feedback(user_id)')


def downgrade():
    raise RuntimeError("Preserve undelivered operation results during rollback.")
