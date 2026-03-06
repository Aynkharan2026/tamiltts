from __future__ import annotations
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Job, JobStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Sanity Webhook"])


def _verify_signature(body: bytes, header: str, secret: str) -> bool:
    if not secret:
        logger.warning("SANITY_WEBHOOK_SECRET not set — skipping signature check")
        return True
    if not header:
        return False
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = parts.get("t", "")
        v1_sig    = parts.get("v1", "")
        signed    = f"{timestamp}.".encode() + body
        expected  = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1_sig)
    except Exception as e:
        logger.error(f"sanity_signature_parse_error: {e}")
        return False


@router.post("/sanity/job-created")
async def sanity_job_created(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()

    sig_header = request.headers.get("sanity-webhook-signature", "")
    if not _verify_signature(raw_body, sig_header, settings.SANITY_WEBHOOK_SECRET):
        logger.warning("sanity_webhook_invalid_signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(raw_body)

    sanity_id = payload.get("_id") or payload.get("id")
    if not sanity_id:
        raise HTTPException(status_code=400, detail="Missing _id in payload")

    existing = db.query(Job).filter(Job.sanity_id == sanity_id).first()
    if existing:
        logger.info(f"sanity_webhook_duplicate sanity_id={sanity_id}")
        return {"status": "duplicate", "job_id": existing.id}

    job_id    = str(uuid.uuid4())
    tenant_id = payload.get("tenantId", "default")
    user_id   = payload.get("userId", "")
    text      = payload.get("originalText", "")
    title     = payload.get("title") or text[:80]
    voice     = payload.get("voiceName", "ta-MY-KaniNeural")
    dialect   = payload.get("dialect", voice[:5] if len(voice) >= 5 else "ta-IN")
    preset    = payload.get("voicePreset")
    callback  = payload.get("callbackUrl")

    if not text:
        raise HTTPException(status_code=400, detail="Missing originalText in Sanity document")

    job = Job(
        id=job_id,
        sanity_id=sanity_id,
        user_id=user_id,
        tenant_id=tenant_id,
        title=title,
        original_text=text,
        voice_mode=voice,
        dialect=dialect,
        preset_id=preset,
        callback_url=callback,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from app.worker.tasks import process_tts_job
    task = process_tts_job.apply_async(args=[job_id])
    job.celery_task_id = task.id
    db.commit()

    logger.info(f"sanity_job_enqueued sanity_id={sanity_id} job_id={job_id}")
    return {"status": "queued", "job_id": job_id, "sanity_id": sanity_id}
