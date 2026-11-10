"""Persist game notices in the same transaction as points and game state."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_game_notices"
down_revision = "0019_room_games"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "game_notices",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("actor_id", sa.BigInteger),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("error", sa.String(64)),
        schema="bot", if_not_exists=True,
    )
    op.create_index("ix_bot_game_notices_chat_id", "game_notices", ["chat_id"], schema="bot", if_not_exists=True)
    op.create_index("ix_bot_game_notices_due_at", "game_notices", ["due_at"], schema="bot", if_not_exists=True)


def downgrade():
    # The previous release ignores this table. Keep pending deliveries for re-upgrade.
    pass
