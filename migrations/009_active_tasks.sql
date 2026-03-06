-- =============================================================================
-- Migration 009: Active Tasks (Concurrency Audit Mirror)
-- Safe: new table only
-- Primary enforcement is Redis counter; this is audit/fallback only
-- =============================================================================

CREATE TABLE IF NOT EXISTS active_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    celery_task_id  VARCHAR(255) UNIQUE NOT NULL,
    task_type       VARCHAR(50) NOT NULL
                    CHECK (task_type IN ('tts','conversation','pdf_bulk')),
    user_id         VARCHAR(36) REFERENCES users(id),
    job_id          VARCHAR(36),
    weight          INTEGER NOT NULL DEFAULT 1,
    started_at      TIMESTAMPTZ DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_active_tasks_running
    ON active_tasks(completed_at) WHERE completed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_active_tasks_celery
    ON active_tasks(celery_task_id);
