import os
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, JobStatus, VoiceMode, ShareToken, User
from app.auth import get_current_user, validate_csrf
from app.config import settings
from app.worker.tasks import process_tts_job

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MAX_TEXT_LENGTH = 100_000  # characters


def _get_user(request: Request, db: Session) -> User:
    return get_current_user(request, db)


def _rate_check(user: User, db: Session):
    """Check if user has exceeded job creation rate limit."""
    recent = (
        db.query(Job)
        .filter(
            Job.user_id == user.id,
            Job.created_at >= datetime.now(timezone.utc).replace(
                hour=max(0, datetime.now(timezone.utc).hour - 1)
            ),
        )
        .count()
    )
    if recent >= settings.RATE_LIMIT_JOBS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Rate limit: too many jobs this hour")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    jobs = (
        db.query(Job)
        .filter(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(50)
        .all()
    )
    from sqlalchemy import text as sql_text
    from app.services.entitlement import can_use_voice_cloning
    user_voices = db.execute(sql_text("""
        SELECT id, display_name, status, tamil_supported, created_at
        FROM voice_models WHERE owner_user_id = :uid AND status != 'disabled'
        ORDER BY created_at DESC
    """), {"uid": user.id}).fetchall()
    can_clone = can_use_voice_cloning(user.id, db)
    return templates.TemplateResponse(
        "dashboard.html", {
            "request": request, "user": user, "jobs": jobs,
            "user_voices": [dict(r._mapping) for r in user_voices],
            "can_clone": can_clone,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_job_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    from sqlalchemy import text as sql_text
    presets = db.execute(sql_text(
        "SELECT preset_key, display_name, emoji, pitch_percent, rate_percent, "
        "volume_percent, tier_required FROM tts_presets WHERE is_active = true "
        "ORDER BY tier_required, display_name"
    )).fetchall()
    plan_row = db.execute(sql_text("""
        SELECT sp.name FROM user_subscriptions us
        JOIN subscription_plans sp ON sp.id = us.plan_id
        WHERE us.user_id = :uid AND us.status = 'active'
    """), {"uid": user.id}).fetchone()
    user_plan = plan_row.name if plan_row else "free"
    return templates.TemplateResponse(
        "new_job.html",
        {
            "request": request,
            "user": user,
            "presets": [dict(r._mapping) for r in presets],
            "voice_modes": list(VoiceMode),
            "user_plan": user_plan,
        },
    )


@router.post("/jobs")
async def create_job(
    request: Request,
    title: str = Form(""),
    text: str = Form(""),
    voice_mode: str   = Form("ta-LK-SaranyaNeural"),
    speed:      float = Form(1.0),
    preset_id:  str   = Form("conversational"),
    dialect:    str   = Form("ta-LK"),
    gender:     str   = Form("female"),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)

    # CSRF validation
    form_data = await request.form()
    validate_csrf(request, form_data.get("csrf_token", ""))

    _rate_check(user, db)

    # Handle file upload
    if file and file.filename:
        if file.size and file.size > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        raw = await file.read(settings.MAX_UPLOAD_BYTES + 1)
        if len(raw) > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")

        filename = file.filename.lower()
        if filename.endswith(".txt"):
            text = raw.decode("utf-8", errors="replace")
        elif filename.endswith(".docx"):
            text = _extract_docx(raw)
        else:
            raise HTTPException(status_code=400, detail="Only .txt and .docx supported")

    # Sanitize & validate text
    text = _sanitize_text(text)
    if len(text) < 10:
        return templates.TemplateResponse(
            "new_job.html",
            {
                "request": request,
                "user": user,
                "voice_modes": list(VoiceMode),
                "presets": [],
                "error": "Text is too short (minimum 10 characters)",
            },
        )
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    # Resolve voice — accept Neural voice names directly OR legacy enum
    if "Neural" in voice_mode:
        try:
            vm = VoiceMode(voice_mode)
        except ValueError:
            vm = VoiceMode.TA_LK_SARANYA  # safe fallback
    else:
        # Legacy enum path
        try:
            vm = VoiceMode(voice_mode)
        except ValueError:
            vm = VoiceMode.TA_LK_SARANYA

    # Clamp speed (expanded range)
    speed = max(0.75, min(1.5, speed))

    # Validate preset — fallback to conversational if invalid
    from sqlalchemy import text as sql_text
    preset_row = db.execute(
        sql_text("SELECT preset_key FROM tts_presets WHERE preset_key = :k AND is_active = true"),
        {"k": preset_id},
    ).fetchone()
    if not preset_row:
        preset_id = "conversational"

    # Create job
    job = Job(
        user_id=user.id,
        title=(title[:255] if title else "Untitled"),
        original_text=text,
        voice_mode=vm,
        speed=speed,
        preset_id=preset_id,
        dialect=dialect,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch to Celery
    task = process_tts_job.delay(job.id)
    job.celery_task_id = task.id
    db.commit()

    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(job_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)

    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    active_tokens = [t for t in job.share_tokens if t.is_active]
    return templates.TemplateResponse(
        "job_detail.html",
        {
            "request": request,
            "user": user,
            "job": job,
            "active_tokens": active_tokens,
        },
    )


@router.get("/download/{job_id}")
async def download_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)

    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job or job.status != JobStatus.DONE:
        raise HTTPException(status_code=404, detail="Audio not ready")

    # P1: Prefer R2 signed URL; fall back to local disk for legacy jobs
    if job.r2_key:
        from app.services.r2_storage import R2StorageService
        from fastapi.responses import RedirectResponse as _Redirect
        r2 = R2StorageService()
        signed = r2.generate_signed_url(job.r2_key)
        return _Redirect(signed["url"], status_code=302)

    if not job.output_path or not os.path.exists(job.output_path):
        raise HTTPException(status_code=404, detail="Audio file missing from disk")

    filename = f"tamiltts_{job_id[:8]}.mp3"
    return FileResponse(
        job.output_path,
        media_type="audio/mpeg",
        filename=filename,
    )


def _sanitize_text(text: str) -> str:
    """Remove null bytes and control chars; normalize whitespace."""
    text = text.replace("\x00", "")
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()


def _extract_docx(raw_bytes: bytes) -> str:
    """Extract plain text from a .docx file."""
    try:
        import zipfile
        import xml.etree.ElementTree as ET
        from io import BytesIO

        z = zipfile.ZipFile(BytesIO(raw_bytes))
        xml_content = z.read("word/document.xml")
        tree = ET.fromstring(xml_content)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        texts = tree.findall(".//w:t", ns)
        return "\n".join(t.text or "" for t in texts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse .docx: {e}")

@router.get("/api/presets")
async def get_presets(request: Request, db: Session = Depends(get_db)):
    from sqlalchemy import text as sql_text
    from app.services.entitlement import can_use_advanced_presets
    try:
        user = _get_user(request, db)
        advanced = can_use_advanced_presets(user.id, db)
    except HTTPException:
        advanced = False
    query = "SELECT preset_key, display_name, emoji, pitch_percent, rate_percent, volume_percent, tier_required FROM tts_presets WHERE is_active = true"
    if not advanced:
        query += " AND tier_required = 'free'"
    query += " ORDER BY created_at ASC"
    rows = db.execute(sql_text(query)).fetchall()
    return [dict(r._mapping) for r in rows]

@router.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    from sqlalchemy import text as sql_text
    import os
    try:
        user = _get_user(request, db)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Not authenticated")

    row = db.execute(sql_text("""
        SELECT id, output_path, user_id, status
        FROM jobs WHERE id = :id AND user_id = :uid
    """), {"id": job_id, "uid": user.id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    if str(row.status) in ("queued", "processing"):
        raise HTTPException(status_code=409, detail="Cannot delete a job that is queued or processing")

    # Delete local output file if exists
    if row.output_path and os.path.exists(row.output_path):
        try:
            os.remove(row.output_path)
        except Exception:
            pass

    # Soft delete active_tasks record
    db.execute(sql_text(
        "DELETE FROM active_tasks WHERE job_id = :id"
    ), {"id": job_id})

    # Delete job record
    db.execute(sql_text(
        "DELETE FROM jobs WHERE id = :id AND user_id = :uid"
    ), {"id": job_id, "uid": user.id})
    db.commit()

    return {"status": "deleted", "job_id": job_id}
