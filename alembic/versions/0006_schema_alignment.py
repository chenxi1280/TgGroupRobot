"""Align legacy production schema with the ORM contract."""
from __future__ import annotations

from alembic import op

revision = "0006_schema_alignment"
down_revision = "0005_ad_rotation_reliability"
branch_labels = None
depends_on = None

GAME_POINTS_SOURCE_FK = "fk_game_settings_points_source_chat_id"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{GAME_POINTS_SOURCE_FK}'
                  AND conrelid = 'bot.game_settings'::regclass
            ) THEN
                ALTER TABLE bot.game_settings
                ADD CONSTRAINT {GAME_POINTS_SOURCE_FK}
                FOREIGN KEY (points_source_chat_id)
                REFERENCES bot.tg_chats(id)
                ON DELETE SET NULL;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE bot.game_settings "
        f"DROP CONSTRAINT IF EXISTS {GAME_POINTS_SOURCE_FK}"
    )
