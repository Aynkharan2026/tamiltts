-- Migration: 002_cms_integration_columns.sql
-- Tamil TTS Studio — SaaS CMS Integration
-- 17488149 CANADA CORP. operating as VoxTN
-- ADDITIVE ONLY — safe to run on live database

BEGIN;

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS article_id       VARCHAR(255)  DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS submitted_by     VARCHAR(255)  DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS callback_url     VARCHAR(512)  DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS idempotency_key  VARCHAR(255)  DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS routing_tags     JSONB         DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS output_filename  VARCHAR(255)  DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS preset_id        VARCHAR(100)  DEFAULT 'conversational',
    ADD COLUMN IF NOT EXISTS dialect          VARCHAR(10)   DEFAULT 'ta-LK';

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency_key
    ON jobs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_article_id
    ON jobs (article_id)
    WHERE article_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_submitted_by
    ON jobs (submitted_by)
    WHERE submitted_by IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_routing_tags
    ON jobs USING GIN (routing_tags);

COMMIT;
