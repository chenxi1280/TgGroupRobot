BEGIN;

ALTER TABLE bot.ad_rotation_rules ADD COLUMN IF NOT EXISTS top_campaign_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE bot.ad_rotation_rules ADD COLUMN IF NOT EXISTS exclude_campaign_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS dispatch_key VARCHAR(128);
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS content_snapshot JSONB;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS rule_snapshot JSONB;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'pending';
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS send_started_at TIMESTAMPTZ;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS error_code VARCHAR(64);
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS replay_of_history_id INTEGER;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS replay_admin_id BIGINT;
ALTER TABLE bot.ad_rotation_history ADD COLUMN IF NOT EXISTS replay_reason TEXT;

UPDATE bot.ad_rotation_history
SET dispatch_key = COALESCE(dispatch_key, 'legacy:' || id::text),
    scheduled_for = COALESCE(scheduled_for, sent_at, created_at, NOW()),
    content_snapshot = COALESCE(content_snapshot, jsonb_build_object('title', title_snapshot)),
    rule_snapshot = COALESCE(rule_snapshot, '{}'::jsonb),
    status = CASE WHEN sent_at IS NOT NULL THEN 'succeeded' ELSE status END,
    attempt_count = CASE WHEN sent_at IS NOT NULL AND attempt_count = 0 THEN 1 ELSE attempt_count END,
    completed_at = COALESCE(completed_at, sent_at)
WHERE dispatch_key IS NULL OR scheduled_for IS NULL OR content_snapshot IS NULL OR rule_snapshot IS NULL;

ALTER TABLE bot.ad_rotation_history ALTER COLUMN dispatch_key SET NOT NULL;
ALTER TABLE bot.ad_rotation_history ALTER COLUMN scheduled_for SET NOT NULL;
ALTER TABLE bot.ad_rotation_history ALTER COLUMN content_snapshot SET NOT NULL;
ALTER TABLE bot.ad_rotation_history ALTER COLUMN rule_snapshot SET NOT NULL;
ALTER TABLE bot.ad_rotation_history ALTER COLUMN sent_at DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ad_rotation_history_dispatch_key ON bot.ad_rotation_history(dispatch_key);
CREATE INDEX IF NOT EXISTS ix_ad_rotation_history_due ON bot.ad_rotation_history(status, next_retry_at, lease_until);

COMMIT;
