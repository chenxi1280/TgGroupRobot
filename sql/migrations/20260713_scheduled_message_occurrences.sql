BEGIN;

ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS run_key VARCHAR(128);
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS scheduled_for BIGINT;
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS content_snapshot JSONB;
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'pending';
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS send_started_at TIMESTAMPTZ;
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE bot.scheduled_message_logs ADD COLUMN IF NOT EXISTS error_code VARCHAR(64);
UPDATE bot.scheduled_message_logs
SET run_key = COALESCE(run_key, 'legacy:' || id::text),
    scheduled_for = COALESCE(scheduled_for, EXTRACT(EPOCH FROM COALESCE(sent_at, NOW()))::bigint),
    content_snapshot = COALESCE(content_snapshot, '{}'::jsonb),
    status = CASE
        WHEN success IS TRUE THEN 'succeeded'
        WHEN success IS FALSE THEN 'permanent_failed'
        ELSE status
    END,
    completed_at = COALESCE(completed_at, sent_at)
WHERE run_key IS NULL OR scheduled_for IS NULL OR content_snapshot IS NULL;
ALTER TABLE bot.scheduled_message_logs ALTER COLUMN run_key SET NOT NULL;
ALTER TABLE bot.scheduled_message_logs ALTER COLUMN scheduled_for SET NOT NULL;
ALTER TABLE bot.scheduled_message_logs ALTER COLUMN content_snapshot SET NOT NULL;
ALTER TABLE bot.scheduled_message_logs ALTER COLUMN sent_at DROP NOT NULL;
ALTER TABLE bot.scheduled_message_logs ALTER COLUMN success DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_sml_run_key ON bot.scheduled_message_logs(run_key);
CREATE INDEX IF NOT EXISTS ix_sml_due ON bot.scheduled_message_logs(status, next_retry_at, lease_until);

COMMIT;
