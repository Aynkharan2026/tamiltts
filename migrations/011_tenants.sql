-- =============================================================================
-- Migration 011: Tenants (Agency/White-label Hook)
-- Safe: new table only, not enforced yet
-- is_active = false on agency plan until launched
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) UNIQUE NOT NULL,
    owner_user_id   VARCHAR(36) NOT NULL REFERENCES users(id),
    plan_id         UUID REFERENCES subscription_plans(id),
    is_active       BOOLEAN NOT NULL DEFAULT false,
    custom_domain   VARCHAR(255),
    feature_flags   JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenants_owner
    ON tenants(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_tenants_slug
    ON tenants(slug);
