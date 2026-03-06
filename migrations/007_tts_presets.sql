-- =============================================================================
-- Migration 007: TTS Presets Registry
-- Safe: new table + seed data
-- =============================================================================

CREATE TABLE IF NOT EXISTS tts_presets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preset_key      VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(255) NOT NULL,
    emoji           VARCHAR(10),
    pitch_percent   INTEGER NOT NULL DEFAULT 0,
    rate_percent    INTEGER NOT NULL DEFAULT 0,
    volume_percent  INTEGER NOT NULL DEFAULT 0,
    pause_ms        INTEGER NOT NULL DEFAULT 350,
    tier_required   VARCHAR(20) NOT NULL DEFAULT 'free'
                    CHECK (tier_required IN ('free','premium','beta')),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now()
);

INSERT INTO tts_presets
    (preset_key, display_name, emoji, pitch_percent, rate_percent, volume_percent, pause_ms, tier_required)
VALUES
-- Free tier presets
('calm_zen',           'Calm / Zen',            '',   -5,  -15,   0,  500, 'free'),
('conversational',     'Conversational',        '',    0,    0,   0,  350, 'free'),
('news_anchor',        'News Anchor',           '',    5,    5,   5,  300, 'free'),
('elearning',          'E-Learning',            '',    0,   -5,   0,  400, 'free'),
('public_alert',       'Public Alert',          '',   10,   10,  15,  250, 'free'),
('whisper',            'Whisper',               '',  -10,  -20, -10,  600, 'free'),
('village_elder',      'Village Elder',         '',  -15,  -20,   0,  700, 'free'),
('grandma',            'Grandma',               '',  -10,  -18,   0,  650, 'free'),
('political_leader',   'Political Leader',      '',    5,   10,  15,  280, 'free'),
('sports_commentator', 'Sports Commentator',    '',   10,   30,  20,  150, 'free'),
-- Premium tier presets
('loving_warm',        'Loving / Warm',         '',   -5,  -10,   0,  450, 'premium'),
('poetry',             'Poetry',                '',   -5,  -15,   0,  600, 'premium'),
('cinema_teaser',      'Cinema Teaser',         '',   -5,  -20,   5,  700, 'premium'),
('radio_dj',           'Radio DJ',              '',    5,   25,  10,  200, 'premium'),
('angry_intense',      'Angry / Intense',       '',   10,   10,  10,  200, 'premium'),
('rude_snarky',        'Rude / Snarky',         '',   10,   20,   5,  180, 'premium'),
('sexy_sultry',        'Sexy / Sultry',         '',   -5,  -10,   0,  500, 'premium'),
('hyper_kid',          'Hyper Kid',             '',   25,   15,  15,  150, 'premium'),
('shy_sweet_kid',      'Shy / Sweet Kid',       '',   20,  -10, -10,  550, 'premium'),
('village_elder_deep', 'Village Elder (Deep)',  '',  -20,  -25,   5,  800, 'premium')
ON CONFLICT (preset_key) DO NOTHING;
