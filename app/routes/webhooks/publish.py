from __future__ import annotations
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Job, JobStatus
from app.services.api_key_auth import validate_api_key
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["VaaS Publish"])

VOICE_MATRIX = {
    "ta-IN": {"male": "ta-IN-ValluvarNeural", "female": "ta-IN-PallaviNeural"},
    "ta-MY": {"male": "ta-MY-SuryaNeural",    "female": "ta-MY-KaniNeural"},
    "ta-LK": {"male": "ta-LK-KumarNeural",    "female": "ta-LK-SaranyaNeural"},
    "ta-SG": {"male": "ta-SG-AnbuNeural",     "female": "ta-SG-VenbaNeural"},
}


class PublishMetadata(BaseModel):
    article_id: Optional[str] = None
    category:   Optional[str] = None
    language:   Optional[str] = "ta"


class PublishRequest(BaseModel):
    text:         str   = Field(..., min_length=10)
    title:        Optional[str] = None
    voice_mode:   str   = Field(default="ta-MY-KaniNeural")
    callback_url: Optional[str] = None
    metadata:     Optional[PublishMetadata] = None


@router.post("/publish")
async def publish(
    body:    PublishRequest,
    request: Request,
    db:      Session = Depends(get_db),
):
    api_key_data = validate_api_key(request, db)
    tenant_id    = api_key_data["tenant_id"]

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        user_id="vaas-api-user-0000-000000000000",
        title=body.title or body.text[:80],
        original_text=body.text,
        voice_mode=body.voice_mode,
        status=JobStatus.QUEUED,
        callback_url=body.callback_url,
        article_id=body.metadata.article_id if body.metadata else None,
        dialect=body.voice_mode[:5] if len(body.voice_mode) >= 5 else "ta-IN",
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from app.worker.tasks import process_tts_job
    task = process_tts_job.apply_async(args=[job_id])
    job.celery_task_id = task.id
    db.commit()

    logger.info(f"VaaS publish: job={job_id} tenant={tenant_id}")
    return {
        "job_id":       job_id,
        "status":       "queued",
        "tenant_id":    tenant_id,
        "submitted_at": job.created_at.isoformat(),
    }
