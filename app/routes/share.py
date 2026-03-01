import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, JobStatus, ShareToken, User
from app.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_user(request: Request, db: Session) -> User:
    return get_current_user(request, db)


@router.post("/share/{job_id}")
async def create_share(
    job_id: str,
    request: Request,
    expires_days: int = Form(0),  # 0 = no expiry
    db: Session = Depends(get_db),
):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)

    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job or job.status != JobStatus.DONE:
        raise HTTPException(status_code=404, detail="Job not found or not ready")

    expires_at = None
    if expires_days and expires_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    token_str = secrets.token_urlsafe(32)
    token = ShareToken(
        job_id=job_id,
        token=token_str,
        is_active=True,
        expires_at=expires_at,
    )
    db.add(token)
    db.commit()

    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/share/{job_id}/revoke")
async def revoke_share(
    job_id: str,
    request: Request,
    token_id: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = _get_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)

    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    share = db.query(ShareToken).filter(
        ShareToken.id == token_id,
        ShareToken.job_id == job_id,
    ).first()
    if share:
        share.is_active = False
        db.commit()

    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.get("/s/{token}", response_class=HTMLResponse)
async def share_page(token: str, request: Request, db: Session = Depends(get_db)):
    share = db.query(ShareToken).filter(
        ShareToken.token == token,
        ShareToken.is_active == True,
    ).first()

    if not share:
        raise HTTPException(status_code=404, detail="Share link not found or revoked")

    now = datetime.now(timezone.utc)
    if share.expires_at and share.expires_at < now:
        raise HTTPException(status_code=410, detail="Share link has expired")

    job = share.job
    return templates.TemplateResponse(
        "share.html",
        {
            "request": request,
            "job": job,
            "token": token,
            "expires_at": share.expires_at,
        },
    )


@router.get("/s/{token}/download")
async def share_download(token: str, db: Session = Depends(get_db)):
    share = db.query(ShareToken).filter(
        ShareToken.token == token,
        ShareToken.is_active == True,
    ).first()

    if not share:
        raise HTTPException(status_code=404, detail="Share link not found or revoked")

    now = datetime.now(timezone.utc)
    if share.expires_at and share.expires_at < now:
        raise HTTPException(status_code=410, detail="Share link has expired")

    job = share.job
    if job.status != JobStatus.DONE or not job.output_path:
        raise HTTPException(status_code=404, detail="Audio not ready")

    if not os.path.exists(job.output_path):
        raise HTTPException(status_code=404, detail="Audio file missing")

    return FileResponse(
        job.output_path,
        media_type="audio/mpeg",
        filename=f"tamiltts_{job.id[:8]}.mp3",
    )
