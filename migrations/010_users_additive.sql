-- =============================================================================
-- Migration 010: Additive columns on users table
-- Safe: nullable columns only, no existing data affected
-- =============================================================================

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS stripe_customer_id  VARCHAR(255),
    ADD COLUMN IF NOT EXISTS ghl_contact_id      VARCHAR(255),
    ADD COLUMN IF NOT EXISTS tenant_id           UUID;

CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
    ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_ghl_contact
    ON users(ghl_contact_id) WHERE ghl_contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_tenant
    ON users(tenant_id) WHERE tenant_id IS NOT NULL;
