from __future__ import annotations
import hashlib
import hmac
import json
import logging
import time
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)
RETRY_DELAYS = [5, 15, 45]

def _sign_payload(body: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    message = f"{ts}.{body}"
    sig = "sha256=" + hmac.new(
        settings.CMS_HMAC_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return ts, sig

async def fire_completion_webhook(callback_url, job_id, article_id, audio_url,
                                   audio_url_expiry, duration_seconds, output_filename,
                                   voice, preset, routing_dispatched, completed_at) -> bool:
    payload = {
        "event": "job.complete", "job_id": job_id, "article_id": article_id,
        "status": "complete", "audio_url": audio_url, "audio_url_expiry": audio_url_expiry,
        "duration_seconds": duration_seconds, "output_filename": output_filename,
        "voice": voice, "preset": preset, "routing_dispatched": routing_dispatched,
        "completed_at": completed_at,
    }
    return await _send_webhook(callback_url, payload)

async def fire_failure_webhook(callback_url, job_id, article_id,
                                error_code, error_detail, failed_at) -> bool:
    payload = {
        "event": "job.failed", "job_id": job_id, "article_id": article_id,
        "status": "failed", "error_code": error_code,
        "error_detail": error_detail, "failed_at": failed_at,
    }
    return await _send_webhook(callback_url, payload)

async def _send_webhook(url: str, payload: dict) -> bool:
    body = json.dumps(payload)
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay > 0:
            import asyncio
            await asyncio.sleep(delay)
        ts, sig = _sign_payload(body)
        headers = {"Content-Type": "application/json",
                   "X-VoxTN-Signature": sig, "X-VoxTN-Timestamp": ts}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, content=body, headers=headers)
                if resp.status_code == 200:
                    logger.info(f"Webhook delivered: {payload.get('event')} attempt={attempt}")
                    return True
                logger.warning(f"Webhook attempt {attempt} got {resp.status_code}")
        except Exception as e:
            logger.warning(f"Webhook attempt {attempt} error: {e}")
    logger.error(f"Webhook delivery failed after all attempts for job {payload.get('job_id')}")
    return False
