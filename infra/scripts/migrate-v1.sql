-- NetSentinel v1 Migration Script
-- Run this to add missing columns for v1 release

-- Add config column to sites for learning_days configuration
ALTER TABLE sites ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}';

-- Add internal_external_ratio to features_5m if missing
ALTER TABLE features_5m ADD COLUMN IF NOT EXISTS internal_external_ratio FLOAT DEFAULT 0.5;

-- Add unique constraint on flows_raw for deduplication (if not exists)
-- This is needed for ON CONFLICT DO NOTHING in flow ingestion
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'flows_raw_dedup_key'
    ) THEN
        -- Create a partial unique index for deduplication
        CREATE UNIQUE INDEX IF NOT EXISTS flows_raw_dedup_idx
        ON flows_raw (site_id, ts_start, src_ip, dst_ip, src_port, dst_port, protocol);
    END IF;
END
$$;

-- Update existing sites to have default learning config
UPDATE sites
SET config = jsonb_build_object('learning_days', 7)
WHERE config IS NULL OR config = '{}';

-- Ensure alert dedup_key column exists
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(255);

-- Create index on dedup_key if not exists
CREATE INDEX IF NOT EXISTS idx_alerts_dedup_key ON alerts(dedup_key) WHERE status = 'open';

-- Add notification_channels column if missing
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notification_channels VARCHAR(50)[];

-- Add notified_at column if missing
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;

COMMIT;
