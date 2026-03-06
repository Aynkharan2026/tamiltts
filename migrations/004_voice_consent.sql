-- =============================================================================
-- Migration 004: Voice Models, Ownership Declarations, Consent, Usage Log
-- Safe: new tables only
-- =============================================================================

CREATE TABLE IF NOT EXISTS voice_models (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id           VARCHAR(36) NOT NULL REFERENCES users(id),
    display_name            VARCHAR(255) NOT NULL,
    elevenlabs_voice_id     VARCHAR(255),
    sample_r2_key           VARCHAR(512),
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','processing','active','disabled')),
    is_public               BOOLEAN NOT NULL DEFAULT false,
    tamil_supported         BOOLEAN NOT NULL DEFAULT false,
    created_at              TIMESTAMPTZ DEFAULT now(),
    disabled_at             TIMESTAMPTZ,
    disabled_by             VARCHAR(36) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS voice_ownership_declarations (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     VARCHAR(36) NOT NULL REFERENCES users(id),
    voice_model_id              UUID NOT NULL REFERENCES voice_models(id),
    declaration_text_version    VARCHAR(50) NOT NULL REFERENCES consent_texts(version),
    declared_at                 TIMESTAMPTZ DEFAULT now(),
    ip_address                  INET,
    user_agent                  VARCHAR(512),
    confirmed                   BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS consent_authorizations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voice_model_id          UUID NOT NULL REFERENCES voice_models(id),
    requester_user_id       VARCHAR(36) NOT NULL REFERENCES users(id),
    owner_user_id           VARCHAR(36) REFERENCES users(id),
    owner_email             VARCHAR(255),
    consent_token_hash      VARCHAR(64) NOT NULL UNIQUE,
    token_expires_at        TIMESTAMPTZ NOT NULL,
    consent_text_version    VARCHAR(50) NOT NULL REFERENCES consent_texts(version),
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','approved','revoked','expired')),
    granted_at              TIMESTAMPTZ,
    revoked_at              TIMESTAMPTZ,
    converted_at            TIMESTAMPTZ,
    ip_address              INET,
    user_agent              VARCHAR(512),
    audit_log               JSONB NOT NULL DEFAULT '[]',
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS voice_usage_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          VARCHAR(36) REFERENCES jobs(id),
    voice_model_id  UUID REFERENCES voice_models(id),
    consent_id      UUID REFERENCES consent_authorizations(id),
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id),
    character_count INTEGER NOT NULL,
    provider        VARCHAR(20) NOT NULL CHECK (provider IN ('elevenlabs','edge_tts')),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_voice_models_owner
    ON voice_models(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_consent_auth_requester
    ON consent_authorizations(requester_user_id);
CREATE INDEX IF NOT EXISTS idx_consent_auth_hash
    ON consent_authorizations(consent_token_hash);
CREATE INDEX IF NOT EXISTS idx_consent_auth_status
    ON consent_authorizations(status);
CREATE INDEX IF NOT EXISTS idx_voice_usage_user
    ON voice_usage_log(user_id, created_at);
