-- =============================================================================
-- Migration 005: Subscription Plans, User Subscriptions, Coupons
-- Safe: new tables only
-- =============================================================================

CREATE TABLE IF NOT EXISTS subscription_plans (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    VARCHAR(100) UNIQUE NOT NULL,
    display_name            VARCHAR(255) NOT NULL,
    monthly_price_cad       NUMERIC(10,2) NOT NULL DEFAULT 0,
    annual_price_cad        NUMERIC(10,2) NOT NULL DEFAULT 0,
    stripe_monthly_price_id VARCHAR(255),
    stripe_annual_price_id  VARCHAR(255),
    ghl_offer_id            VARCHAR(255),
    is_active               BOOLEAN NOT NULL DEFAULT true,
    is_beta                 BOOLEAN NOT NULL DEFAULT false,
    beta_expires_at         TIMESTAMPTZ,
    beta_max_users          INTEGER,
    feature_flags           JSONB NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(36) UNIQUE NOT NULL REFERENCES users(id),
    plan_id                 UUID NOT NULL REFERENCES subscription_plans(id),
    status                  VARCHAR(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','cancelled','expired','trialing')),
    billing_cycle           VARCHAR(10) DEFAULT 'none'
                            CHECK (billing_cycle IN ('monthly','annual','none')),
    stripe_subscription_id  VARCHAR(255),
    stripe_customer_id      VARCHAR(255),
    current_period_start    TIMESTAMPTZ,
    current_period_end      TIMESTAMPTZ,
    trial_ends_at           TIMESTAMPTZ,
    cancelled_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coupons (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code                VARCHAR(50) UNIQUE NOT NULL,
    description         VARCHAR(255),
    discount_type       VARCHAR(10) NOT NULL CHECK (discount_type IN ('percent','fixed')),
    discount_value      NUMERIC(10,2) NOT NULL,
    applies_to          VARCHAR(10) NOT NULL DEFAULT 'both'
                        CHECK (applies_to IN ('monthly','annual','both')),
    max_redemptions     INTEGER,
    max_per_user        INTEGER NOT NULL DEFAULT 1,
    stackable           BOOLEAN NOT NULL DEFAULT false,
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_until         TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    is_beta             BOOLEAN NOT NULL DEFAULT false,
    plan_id             UUID REFERENCES subscription_plans(id),
    stripe_coupon_id    VARCHAR(255),
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coupon_id           UUID NOT NULL REFERENCES coupons(id),
    user_id             VARCHAR(36) NOT NULL REFERENCES users(id),
    subscription_id     UUID REFERENCES user_subscriptions(id),
    redeemed_at         TIMESTAMPTZ DEFAULT now(),
    discount_applied    NUMERIC(10,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user
    ON user_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_plan
    ON user_subscriptions(plan_id);
CREATE INDEX IF NOT EXISTS idx_coupon_code
    ON coupons(code);
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_user
    ON coupon_redemptions(user_id, coupon_id);

-- Seed subscription plans
INSERT INTO subscription_plans (name, display_name, monthly_price_cad, annual_price_cad, is_active, is_beta, feature_flags)
VALUES
(
    'free',
    'Free',
    0, 0,
    true, false,
    '{
        "voice_cloning": false,
        "multi_speaker": false,
        "advanced_presets": false,
        "bulk_pdf": false,
        "watermark": true,
        "max_speakers": 1,
        "elevenlabs_monthly_chars": 0
    }'::jsonb
),
(
    'premium',
    'Premium',
    19.00, 179.00,
    true, false,
    '{
        "voice_cloning": true,
        "multi_speaker": true,
        "advanced_presets": true,
        "bulk_pdf": true,
        "watermark": false,
        "max_speakers": 5,
        "elevenlabs_monthly_chars": 10000
    }'::jsonb
),
(
    'beta',
    'Beta (Limited)',
    0, 0,
    true, true,
    '{
        "voice_cloning": true,
        "multi_speaker": true,
        "advanced_presets": true,
        "bulk_pdf": true,
        "watermark": false,
        "max_speakers": 5,
        "elevenlabs_monthly_chars": 10000
    }'::jsonb
),
(
    'agency',
    'Agency',
    99.00, 899.00,
    false, false,
    '{
        "voice_cloning": true,
        "multi_speaker": true,
        "advanced_presets": true,
        "bulk_pdf": true,
        "watermark": false,
        "max_speakers": 5,
        "elevenlabs_monthly_chars": 50000,
        "multi_tenant": true,
        "white_label": true
    }'::jsonb
)
ON CONFLICT (name) DO NOTHING;
