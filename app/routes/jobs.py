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
from app.auth import get_current_user
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
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "user": user, "jobs": jobs}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_job_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "new_job.html",
        {"request": request, "user": user, "voice_modes": list(VoiceMode)},
    )


@router.post("/jobs")
async def create_job(
    request: Request,
    title: str = Form(""),
    text: str = Form(""),
    voice_mode: str = Form(...),
    speed: float = Form(1.0),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)

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
                "error": "Text is too short (minimum 10 characters)",
            },
        )
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    # Validate voice mode
    try:
        vm = VoiceMode(voice_mode)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid voice mode")

    # Clamp speed
    speed = max(0.9, min(1.1, speed))

    # Create job
    job = Job(
        user_id=user.id,
        title=(title[:255] if title else "Untitled"),
        original_text=text,
        voice_mode=vm,
        speed=speed,
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
    if not job or job.status != JobStatus.DONE or not job.output_path:
        raise HTTPException(status_code=404, detail="Audio not ready")

    if not os.path.exists(job.output_path):
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
