"""Durable generic admin plans, tag ownership and explicit reminder consent."""
from alembic import op

revision = '0017_generic_admin_delivery'
down_revision = '0016_delivery_action_facts'
branch_labels = None
depends_on = None

STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS bot.admin_effects (
        id BIGSERIAL PRIMARY KEY, effect_key VARCHAR(128) NOT NULL UNIQUE,
        chat_id BIGINT NOT NULL, kind VARCHAR(32) NOT NULL, payload JSONB NOT NULL,
        status VARCHAR(32) NOT NULL, attempts INTEGER NOT NULL, next_run_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ, lease_until TIMESTAMPTZ, started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ, result JSONB NOT NULL, error TEXT)''',
    'CREATE INDEX IF NOT EXISTS ix_admin_effect_due ON bot.admin_effects (status, next_run_at)',
    'CREATE INDEX IF NOT EXISTS ix_bot_admin_effects_chat_id ON bot.admin_effects (chat_id)',
    '''CREATE TABLE IF NOT EXISTS bot.level_tag_states (
        chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, applied_tag VARCHAR(16),
        desired_tag VARCHAR(16) NOT NULL, status VARCHAR(32) NOT NULL, error TEXT,
        checked_at TIMESTAMPTZ NOT NULL, retry_at TIMESTAMPTZ, PRIMARY KEY (chat_id,user_id))''',
    '''CREATE TABLE IF NOT EXISTS bot.notice_consents (
        chat_id BIGINT NOT NULL, ad_id INTEGER NOT NULL, user_id BIGINT NOT NULL,
        version VARCHAR(32) NOT NULL, enabled BOOLEAN NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (chat_id,ad_id,user_id))''',
    "ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS expiry_notice jsonb NOT NULL DEFAULT '{}'::jsonb",
)


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    raise RuntimeError('Retain administrative plans, tag ownership and consent; use a compatible forward repair.')
