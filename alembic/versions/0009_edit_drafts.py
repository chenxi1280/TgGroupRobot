"""Keep suspended editor payloads independently of legacy active inputs."""
from alembic import op

revision = "0009_edit_drafts"
down_revision = "0008_mall_confirmation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE IF NOT EXISTS bot.edit_drafts (
        token varchar(32) PRIMARY KEY,
        user_id bigint NOT NULL REFERENCES bot.tg_users(id) ON DELETE CASCADE,
        chat_id bigint NOT NULL,
        state_chat_id bigint NOT NULL,
        state_type varchar(64) NOT NULL,
        state_data jsonb NOT NULL,
        expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL
    )''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_edit_drafts_user_id ON bot.edit_drafts(user_id)')


def downgrade():
    raise RuntimeError("Preserve user drafts during rollback.")
