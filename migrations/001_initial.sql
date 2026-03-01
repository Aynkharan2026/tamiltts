-- TamilTTS Studio — Initial Schema
-- Run with: psql $DATABASE_URL -f migrations/001_initial.sql

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Users
CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(36)  PRIMARY KEY DEFAULT gen_random_uuid()::text,
    email           VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Enums
DO $$ BEGIN
    CREATE TYPE job_status AS ENUM ('queued','processing','done','failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE voice_mode AS ENUM (
        'male_newsreader','male_conversational',
        'female_newsreader','female_conversational'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE chunk_status AS ENUM ('pending','done','failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Jobs
CREATE TABLE IF NOT EXISTS jobs (
    id             VARCHAR(36)  PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id        VARCHAR(36)  NOT NULL REFERENCES users(id),
    title          VARCHAR(255),
    original_text  TEXT NOT NULL,
    voice_mode     voice_mode   NOT NULL,
    speed          FLOAT        NOT NULL DEFAULT 1.0,
    status         job_status   NOT NULL DEFAULT 'queued',
    error_message  TEXT,
    output_path    VARCHAR(512),
    celery_task_id VARCHAR(255),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

-- Job Chunks
CREATE TABLE IF NOT EXISTS job_chunks (
    id            VARCHAR(36)  PRIMARY KEY DEFAULT gen_random_uuid()::text,
    job_id        VARCHAR(36)  NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    chunk_index   INTEGER      NOT NULL,
    text          TEXT         NOT NULL,
    status        chunk_status NOT NULL DEFAULT 'pending',
    output_path   VARCHAR(512),
    error_message TEXT,
    attempts      INTEGER      NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_job_id  ON job_chunks(job_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_job_idx ON job_chunks(job_id, chunk_index);

-- Share Tokens
CREATE TABLE IF NOT EXISTS share_tokens (
    id         VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    job_id     VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    token      VARCHAR(64) NOT NULL UNIQUE,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_share_tokens_token  ON share_tokens(token);
CREATE INDEX IF NOT EXISTS idx_share_tokens_job_id ON share_tokens(job_id);

COMMIT;
