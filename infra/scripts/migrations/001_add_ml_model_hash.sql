-- Migration: Add content_hash to baseline_models table
-- This enables model versioning based on content fingerprint

-- Add content_hash column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'baseline_models' AND column_name = 'content_hash'
    ) THEN
        ALTER TABLE baseline_models ADD COLUMN content_hash VARCHAR(64);
    END IF;
END $$;

-- Add unique constraint on site_id + model_type + version
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_models_site_type_version'
    ) THEN
        CREATE UNIQUE INDEX idx_models_site_type_version
        ON baseline_models(site_id, model_type, model_version);
    END IF;
END $$;

-- Add index for quick model lookup
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_models_hash'
    ) THEN
        CREATE INDEX idx_models_hash ON baseline_models(content_hash);
    END IF;
END $$;
