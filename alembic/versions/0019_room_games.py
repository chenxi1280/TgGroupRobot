"""Persist room sessions and platform fee receipts."""
from alembic import op

from backend.platform.db.schema.models.room_games import PlatformGameFee, RoomGame

revision = "0019_room_games"
down_revision = "0018_mini_app_verification"
branch_labels = None
depends_on = None


def upgrade():
    for model in (RoomGame, PlatformGameFee):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Retain room settlements and fee receipts; use a forward migration.")
