"""Durable mall confirmations; one intent consumes at most one order."""
from alembic import op

revision = "0008_mall_confirmation"
down_revision = "0007_ops_module_config_prompt"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE IF NOT EXISTS bot.points_mall_intents (
        token varchar(32) PRIMARY KEY,
        chat_id bigint NOT NULL REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
        buyer_user_id bigint NOT NULL REFERENCES bot.tg_users(id) ON DELETE CASCADE,
        product_id integer NOT NULL,
        terms jsonb NOT NULL,
        expires_at timestamptz NOT NULL,
        order_id integer NULL REFERENCES bot.points_mall_orders(order_id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL,
        CONSTRAINT uq_mall_intent_order UNIQUE (order_id)
    )''')


def downgrade():
    raise RuntimeError("Keep confirmation records during rollback; use compatible application code.")
