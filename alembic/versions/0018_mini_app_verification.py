"""Track member web verification separately from Telegram timeout delivery."""
from alembic import op

revision = "0018_mini_app_verification"
down_revision = "0017_generic_admin_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE bot.verification_challenges ADD COLUMN mini_app_status VARCHAR(32)")


def downgrade():
    raise RuntimeError("Retain verification resolution records; use a forward migration.")
