"""
Concurrency Guard
Tamil TTS Studio — VoxTN

Protects the 4GB Hetzner VPS from overload.
Primary enforcement: Redis atomic counter (active_task_weight)
Fallback/audit:      active_tasks DB table

Weight system:
  standard TTS job  = weight 1
  conversation job  = weight 2
  pdf_bulk job      = weight 2
  total cap         = 2

This means: 2 standard jobs OR 1 heavy job can run simultaneously.
"""
import logging
import redis as redis_lib
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REDIS_WEIGHT_KEY = "active_task_weight"
MAX_WEIGHT       = 2

TASK_WEIGHTS = {
    "tts":          1,
    "conversation": 2,
    "pdf_bulk":     2,
}


def get_redis():
    import os
    return redis_lib.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/2"))


def current_weight() -> int:
    """Return current total active task weight from Redis."""
    r = get_redis()
    val = r.get(REDIS_WEIGHT_KEY)
    return int(val) if val else 0


def can_accept(task_type: str) -> bool:
    """Return True if a new task of this type can be accepted."""
    weight = TASK_WEIGHTS.get(task_type, 1)
    return (current_weight() + weight) <= MAX_WEIGHT


def acquire(task_type: str, celery_task_id: str, user_id: str,
            job_id: str, db: Session) -> bool:
    """
    Atomically acquire a concurrency slot.
    Returns True if slot acquired, False if at capacity.
    """
    weight = TASK_WEIGHTS.get(task_type, 1)
    r = get_redis()

    # Lua script: atomic check-and-increment
    lua = """
        local current = tonumber(redis.call('GET', KEYS[1]) or 0)
        local weight = tonumber(ARGV[1])
        local cap = tonumber(ARGV[2])
        if current + weight > cap then
            return 0
        end
        redis.call('INCRBY', KEYS[1], weight)
        return 1
    """
    result = r.eval(lua, 1, REDIS_WEIGHT_KEY, weight, MAX_WEIGHT)

    if not result:
        logger.warning(
            "concurrency_guard: REJECTED task_type=%s weight=%d current=%d cap=%d",
            task_type, weight, current_weight(), MAX_WEIGHT,
        )
        return False

    # Mirror to DB for audit
    try:
        db.execute(
            text("""
                INSERT INTO active_tasks
                    (celery_task_id, task_type, user_id, job_id, weight, started_at)
                VALUES
                    (:task_id, :task_type, :user_id, :job_id, :weight, :started_at)
            """),
            {
                "task_id":    celery_task_id,
                "task_type":  task_type,
                "user_id":    user_id,
                "job_id":     job_id,
                "weight":     weight,
                "started_at": datetime.now(timezone.utc),
            },
        )
        db.commit()
    except Exception as e:
        logger.error("concurrency_guard: DB mirror failed: %s", e)

    logger.info(
        "concurrency_guard: ACQUIRED task_type=%s weight=%d new_total=%d",
        task_type, weight, current_weight(),
    )
    return True


def release(task_type: str, celery_task_id: str, db: Session) -> None:
    """Release a concurrency slot when a task completes or fails."""
    weight = TASK_WEIGHTS.get(task_type, 1)
    r = get_redis()

    # Decrement but never below 0
    lua = """
        local current = tonumber(redis.call('GET', KEYS[1]) or 0)
        local weight = tonumber(ARGV[1])
        local new_val = math.max(0, current - weight)
        redis.call('SET', KEYS[1], new_val)
        return new_val
    """
    new_val = r.eval(lua, 1, REDIS_WEIGHT_KEY, weight)

    # Mark complete in DB
    try:
        db.execute(
            text("""
                UPDATE active_tasks
                SET completed_at = :now
                WHERE celery_task_id = :task_id
                  AND completed_at IS NULL
            """),
            {"now": datetime.now(timezone.utc), "task_id": celery_task_id},
        )
        db.commit()
    except Exception as e:
        logger.error("concurrency_guard: DB release failed: %s", e)

    logger.info(
        "concurrency_guard: RELEASED task_type=%s weight=%d remaining=%d",
        task_type, weight, new_val,
    )


def check_status() -> dict:
    """
    Health check: return current concurrency state.
    Use this in monitoring commands.
    """
    return {
        "active_weight": current_weight(),
        "max_weight":    MAX_WEIGHT,
        "available":     MAX_WEIGHT - current_weight(),
        "weights":       TASK_WEIGHTS,
    }
