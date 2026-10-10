"""Durable publication identity and outcome, independent of activity state."""
from alembic import op
revision = "0010_activity_publications"
down_revision = "0009_edit_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE IF NOT EXISTS bot.activity_publications (
        token varchar(32) PRIMARY KEY, domain varchar(16) NOT NULL,
        chat_id bigint NOT NULL, creator_user_id bigint NOT NULL,
        entity_id integer NULL, status varchar(32) NOT NULL,
        payload jsonb NOT NULL, message_id bigint NULL, error text NULL,
        updated_at timestamptz NOT NULL
    )''')


def downgrade():
    raise RuntimeError("Preserve publication identities and unknown results during rollback.")
