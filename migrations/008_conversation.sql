-- =============================================================================
-- Migration 008: Multi-Speaker Conversation Tables
-- Safe: new tables only
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversation_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_job_id   VARCHAR(36) REFERENCES jobs(id),
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id),
    input_mode      VARCHAR(15) NOT NULL CHECK (input_mode IN ('markup','structured')),
    speaker_count   INTEGER NOT NULL CHECK (speaker_count BETWEEN 1 AND 5),
    total_chars     INTEGER NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','processing','done','failed')),
    output_r2_key   VARCHAR(512),
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversation_speakers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversation_jobs(id) ON DELETE CASCADE,
    speaker_index   INTEGER NOT NULL CHECK (speaker_index BETWEEN 0 AND 4),
    label           VARCHAR(50) NOT NULL,
    voice_model_id  UUID REFERENCES voice_models(id),
    edge_tts_voice  VARCHAR(100),
    preset_key      VARCHAR(100) REFERENCES tts_presets(preset_key),
    pitch_offset    INTEGER NOT NULL DEFAULT 0,
    rate_modifier   FLOAT NOT NULL DEFAULT 1.0,
    volume_db       FLOAT NOT NULL DEFAULT 0.0,
    CONSTRAINT speaker_has_voice CHECK (
        voice_model_id IS NOT NULL OR edge_tts_voice IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS conversation_segments (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id         UUID NOT NULL REFERENCES conversation_jobs(id) ON DELETE CASCADE,
    speaker_index           INTEGER NOT NULL,
    sequence_order          INTEGER NOT NULL,
    text                    TEXT NOT NULL,
    char_count              INTEGER NOT NULL,
    sanitized_char_count    INTEGER,
    segment_r2_key          VARCHAR(512),
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','done','failed')),
    duration_ms             INTEGER,
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_jobs_user
    ON conversation_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_jobs_status
    ON conversation_jobs(status);
CREATE INDEX IF NOT EXISTS idx_conv_segments_conv
    ON conversation_segments(conversation_id, sequence_order);
CREATE INDEX IF NOT EXISTS idx_conv_speakers_conv
    ON conversation_speakers(conversation_id, speaker_index);
