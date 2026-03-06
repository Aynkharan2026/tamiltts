-- =============================================================================
-- Migration 003: Consent Text Registry
-- Safe: new table only
-- =============================================================================
CREATE TABLE IF NOT EXISTS consent_texts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version         VARCHAR(50) UNIQUE NOT NULL,
    effective_date  TIMESTAMPTZ NOT NULL,
    body_text       TEXT NOT NULL,
    created_by      VARCHAR(36),
    created_at      TIMESTAMPTZ DEFAULT now()
);
