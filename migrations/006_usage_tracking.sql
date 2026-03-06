-- =============================================================================
-- Migration 006: Usage Tracking
-- Safe: new table only
-- =============================================================================

CREATE TABLE IF NOT EXISTS usage_tracking (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             VARCHAR(36) NOT NULL REFERENCES users(id),
    period_start        TIMESTAMPTZ NOT NULL,
    period_end          TIMESTAMPTZ NOT NULL,
    chars_tts_total     INTEGER NOT NULL DEFAULT 0,
    chars_elevenlabs    INTEGER NOT NULL DEFAULT 0,
    jobs_created        INTEGER NOT NULL DEFAULT 0,
    jobs_elevenlabs     INTEGER NOT NULL DEFAULT 0,
    abuse_flag          BOOLEAN NOT NULL DEFAULT false,
    abuse_reason        VARCHAR(255),
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_tracking_window
    ON usage_tracking(user_id, period_start);
CREATE INDEX IF NOT EXISTS idx_usage_tracking_user_time
    ON usage_tracking(user_id, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_usage_abuse_flag
    ON usage_tracking(abuse_flag) WHERE abuse_flag = true;
