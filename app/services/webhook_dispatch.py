from __future__ import annotations
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

BACKOFF_MINUTES = [int(x) for x in settings.WEBHOOK_RETRY_BACKOFF.split(",")]


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def dispatch_webhook(
    db: Session,
    job_id: str,
    tenant_id: str,
    callback_url: str,
    payload: dict,
) -> None:
    """Fire outbound webhook and record delivery attempt."""
    payload_str = json.dumps(payload, default=str)
    secret = _get_tenant_secret(db, tenant_id)
    signature = _sign(payload_str, secret) if secret else ""

    delivery_id = _create_delivery(db, job_id, tenant_id, callback_url, payload)

    try:
        headers = {
            "Content-Type": "application/json",
            "X-TamilTTS-Job-ID": job_id,
            "X-TamilTTS-Tenant": tenant_id,
        }
        if signature:
            headers["X-TamilTTS-Signature"] = signature

        with httpx.Client(timeout=10) as client:
            resp = client.post(callback_url, content=payload_str, headers=headers)
            resp.raise_for_status()

        _mark_delivered(db, delivery_id)
        logger.info(f"Webhook delivered: job={job_id} url={callback_url}")

    except Exception as e:
        _schedule_retry(db, delivery_id, attempt=1, error=str(e))
        logger.warning(f"Webhook failed (attempt 1): job={job_id} error={e}")


def retry_pending_webhooks(db: Session) -> int:
    """Called by Celery beat every 5 minutes. Returns count of retried."""
    now = datetime.now(timezone.utc)
    rows = db.execute(
        text("""
            SELECT id, job_id, tenant_id, callback_url, payload, attempts
            FROM webhook_deliveries
            WHERE status = 'pending'
              AND (next_retry_at IS NULL OR next_retry_at <= :now)
              AND attempts < :max_attempts
        """),
        {"now": now, "max_attempts": settings.WEBHOOK_RETRY_COUNT},
    ).fetchall()

    count = 0
    for row in rows:
        payload_str = json.dumps(row.payload, default=str)
        secret = _get_tenant_secret(db, row.tenant_id)
        signature = _sign(payload_str, secret) if secret else ""
        try:
            headers = {
                "Content-Type": "application/json",
                "X-TamilTTS-Job-ID": row.job_id,
            }
            if signature:
                headers["X-TamilTTS-Signature"] = signature
            with httpx.Client(timeout=10) as client:
                resp = client.post(row.callback_url, content=payload_str, headers=headers)
                resp.raise_for_status()
            _mark_delivered(db, row.id)
            count += 1
        except Exception as e:
            next_attempt = row.attempts + 1
            if next_attempt >= settings.WEBHOOK_RETRY_COUNT:
                _mark_failed(db, row.id, str(e))
            else:
                _schedule_retry(db, row.id, next_attempt, str(e))
    return count


def _get_tenant_secret(db: Session, tenant_id: str) -> str:
    row = db.execute(
        text("SELECT feature_flags FROM tenants WHERE id::text = :tid OR slug = :tid"),
        {"tid": tenant_id},
    ).fetchone()
    if row and row.feature_flags:
        return row.feature_flags.get("webhook_secret", "")
    return ""


def _create_delivery(db, job_id, tenant_id, callback_url, payload) -> str:
    row = db.execute(
        text("""
            INSERT INTO webhook_deliveries
                (job_id, tenant_id, callback_url, payload, status, attempts)
            VALUES (:job_id, :tenant_id, :url, :payload, 'pending', 0)
            RETURNING id
        """),
        {"job_id": job_id, "tenant_id": tenant_id,
         "url": callback_url, "payload": json.dumps(payload, default=str)},
    ).fetchone()
    db.commit()
    return str(row.id)


def _mark_delivered(db, delivery_id: str):
    db.execute(
        text("""
            UPDATE webhook_deliveries
            SET status = 'delivered', delivered_at = NOW(),
                attempts = attempts + 1
            WHERE id = :id
        """),
        {"id": delivery_id},
    )
    db.commit()


def _schedule_retry(db, delivery_id: str, attempt: int, error: str):
    delay = BACKOFF_MINUTES[min(attempt - 1, len(BACKOFF_MINUTES) - 1)]
    next_retry = datetime.now(timezone.utc) + timedelta(minutes=delay)
    db.execute(
        text("""
            UPDATE webhook_deliveries
            SET attempts = attempts + 1,
                last_error = :error,
                next_retry_at = :next_retry
            WHERE id = :id
        """),
        {"error": error[:500], "next_retry": next_retry, "id": delivery_id},
    )
    db.commit()


def _mark_failed(db, delivery_id: str, error: str):
    db.execute(
        text("""
            UPDATE webhook_deliveries
            SET status = 'callback_failed',
                attempts = attempts + 1,
                last_error = :error
            WHERE id = :id
        """),
        {"error": error[:500], "id": delivery_id},
    )
    db.commit()
