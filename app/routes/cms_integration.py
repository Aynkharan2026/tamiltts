from __future__ import annotations
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.models import Job, JobStatus
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tts", tags=["CMS Integration"])

CMS_SYSTEM_USER_ID = "cms-system-user-0000-000000000000"
VALID_DIALECTS = {"ta-IN", "ta-MY", "ta-LK", "ta-SG"}
VALID_GENDERS  = {"male", "female"}
VALID_PRESETS  = {
    "calm_zen","rude_snarky","poetry","sexy_sultry","angry_intense",
    "loving_warm","news_anchor","village_elder","cinema_teaser",
    "elearning","radio_dj","whisper","public_alert","conversational",
    "hyper_kid","shy_sweet_kid",
}
VOICE_MATRIX = {
    "ta-IN": {"male": "ta-IN-ValluvarNeural",  "female": "ta-IN-PallaviNeural"},
    "ta-MY": {"male": "ta-MY-SuryaNeural",     "female": "ta-MY-KaniNeural"},
    "ta-LK": {"male": "ta-LK-KumarNeural",     "female": "ta-LK-SaranyaNeural"},
    "ta-SG": {"male": "ta-SG-AnbuNeural",      "female": "ta-SG-VenbaNeural"},
}
PRESET_SPEEDS = {
    "calm_zen":0.85,"rude_snarky":1.20,"poetry":0.80,"sexy_sultry":0.90,
    "angry_intense":1.00,"loving_warm":0.90,"news_anchor":1.05,"village_elder":0.85,
    "cinema_teaser":0.80,"elearning":0.95,"radio_dj":1.25,"whisper":0.70,
    "public_alert":1.10,"conversational":1.00,"hyper_kid":1.15,"shy_sweet_kid":0.90,
}
TIMESTAMP_TOLERANCE = 300

class RoutingTags(BaseModel):
    section:     Optional[str]       = None
    author_role: Optional[str]       = None
    tags:        Optional[list[str]] = Field(default_factory=list)

class CMSJobRequest(BaseModel):
    article_id:      str   = Field(..., min_length=1, max_length=255)
    title:           str   = Field(..., min_length=1, max_length=500)
    body:            str   = Field(..., min_length=50)
    dialect:         str   = Field(...)
    voice_gender:    str   = Field(...)
    preset:          str   = Field(default="conversational")
    output_filename: Optional[str] = None
    routing_tags:    Optional[RoutingTags] = None
    callback_url:    str   = Field(...)
    submitted_by:    str   = Field(...)
    idempotency_key: Optional[str] = None

    @validator("dialect")
    def v_dialect(cls, v):
        if v not in VALID_DIALECTS:
            raise ValueError(f"dialect must be one of {VALID_DIALECTS}")
        return v

    @validator("voice_gender")
    def v_gender(cls, v):
        if v not in VALID_GENDERS:
            raise ValueError(f"voice_gender must be one of {VALID_GENDERS}")
        return v

    @validator("preset")
    def v_preset(cls, v):
        if v not in VALID_PRESETS:
            raise ValueError(f"preset must be one of {VALID_PRESETS}")
        return v

    @validator("output_filename")
    def v_filename(cls, v):
        if v is None:
            return v
        import re
        cleaned = re.sub(r"[^\w\u0B80-\u0BFF\-]", "-", v)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        return (cleaned[:200] if cleaned else None)

def verify_hmac(body: bytes, sig_header: Optional[str], ts_header: Optional[str]):
    if not sig_header or not ts_header:
        raise HTTPException(status_code=401, detail="INVALID_SIGNATURE")
    try:
        ts = int(ts_header)
    except ValueError:
        raise HTTPException(status_code=401, detail="INVALID_SIGNATURE")
    if abs(int(time.time()) - ts) > TIMESTAMP_TOLERANCE:
        raise HTTPException(status_code=401, detail="INVALID_SIGNATURE")
    message = f"{ts_header}.{body.decode('utf-8')}"
    expected = "sha256=" + hmac.new(
        settings.CMS_HMAC_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_header):
        raise HTTPException(status_code=401, detail="INVALID_SIGNATURE")

@router.post("/jobs", status_code=202)
async def submit_cms_job(
    request: Request,
    db: Session = Depends(get_db),
    x_voxtn_signature: Optional[str] = Header(None),
    x_voxtn_timestamp: Optional[str] = Header(None),
):
    body_bytes = await request.body()
    verify_hmac(body_bytes, x_voxtn_signature, x_voxtn_timestamp)
    try:
        payload = CMSJobRequest(**json.loads(body_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"INVALID_PAYLOAD: {e}")

    idem_key = payload.idempotency_key or f"{payload.article_id}-{payload.submitted_by}"
    existing = db.query(Job).filter(Job.idempotency_key == idem_key).first()
    if existing:
        return {"job_id": existing.id, "status": existing.status.value,
                "article_id": existing.article_id, "queued_at": existing.created_at.isoformat(),
                "note": "existing_job"}

    voice           = VOICE_MATRIX[payload.dialect][payload.voice_gender]
    output_filename = (payload.output_filename or f"{payload.article_id}-{int(time.time())}") + ".mp3"
    if output_filename.endswith(".mp3.mp3"):
        output_filename = output_filename[:-4]

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        user_id=CMS_SYSTEM_USER_ID,
        title=payload.title,
        original_text=payload.body,
        voice_mode=voice,
        speed=PRESET_SPEEDS.get(payload.preset, 1.0),
        status=JobStatus.QUEUED,
        article_id=payload.article_id,
        submitted_by=payload.submitted_by,
        callback_url=payload.callback_url,
        idempotency_key=idem_key,
        routing_tags=payload.routing_tags.dict() if payload.routing_tags else {},
        output_filename=output_filename,
        preset_id=payload.preset,
        dialect=payload.dialect,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from app.worker.tasks import process_tts_job
    task = process_tts_job.apply_async(
        args=[job_id],
        kwargs={
            "preset_id":       payload.preset,
            "output_filename": output_filename,
            "routing_tags":    payload.routing_tags.dict() if payload.routing_tags else {},
            "callback_url":    payload.callback_url,
            "article_id":      payload.article_id,
        }
    )
    job.celery_task_id = task.id
    db.commit()

    chars = len(payload.body)
    estimated = max(15, min(int(chars / 300) + 10, 300))
    logger.info(f"CMS job {job_id} created for article {payload.article_id}")
    return {"job_id": job_id, "status": "queued",
            "article_id": payload.article_id,
            "queued_at": job.created_at.isoformat(),
            "estimated_seconds": estimated}

@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_voxtn_signature: Optional[str] = Header(None),
    x_voxtn_timestamp: Optional[str] = Header(None),
):
    body_bytes = await request.body()
    verify_hmac(body_bytes or b"", x_voxtn_signature, x_voxtn_timestamp)
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    result = {
        "job_id": job.id, "article_id": job.article_id,
        "status": job.status.value, "output_filename": job.output_filename,
        "voice": job.voice_mode, "preset": job.preset_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "error_message": job.error_message,
    }
    if job.status == JobStatus.DONE and job.output_path:
        from app.services.r2_storage import R2StorageService
        signed = R2StorageService().generate_signed_url(job.output_path)
        result["audio_url"]        = signed["url"]
        result["audio_url_expiry"] = signed["expires_at"]
    return result

@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_voxtn_signature: Optional[str] = Header(None),
    x_voxtn_timestamp: Optional[str] = Header(None),
):
    body_bytes = await request.body()
    verify_hmac(body_bytes or b"", x_voxtn_signature, x_voxtn_timestamp)
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    r2_deleted = False
    if job.output_path:
        try:
            from app.services.r2_storage import R2StorageService
            R2StorageService().delete_object(job.output_path)
            r2_deleted = True
        except Exception as e:
            logger.error(f"R2 delete failed: {e}")
    db.delete(job)
    db.commit()
    return {"job_id": job_id, "deleted": True, "r2_asset_deleted": r2_deleted}

@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded",
            "db": "ok" if db_ok else "error",
            "timestamp": int(time.time())}
