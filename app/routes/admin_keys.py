from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.services.api_key_auth import generate_api_key
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Admin Keys"])


def _require_internal(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    expected = getattr(settings, "INTERNAL_API_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


class CreateKeyRequest(BaseModel):
    display_name: str
    tenant_id: str | None = None
    expires_at: str | None = None


@router.post("/keys")
def create_api_key(
    body: CreateKeyRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    _require_internal(request)

    # Resolve tenant_id from clerk_user_id if not provided
    tenant_id = body.tenant_id
    if not tenant_id and x_clerk_user_id:
        row = db.execute(
            text("""
                SELECT t.id FROM tenants t
                JOIN users u ON t.owner_user_id = u.id
                WHERE u.clerk_user_id = :cuid AND t.is_active = true
                LIMIT 1
            """),
            {"cuid": x_clerk_user_id},
        ).fetchone()
        if row:
            tenant_id = str(row.id)

    if not tenant_id:
        tenant_id = x_clerk_user_id or "default"

    raw_key, key_hash, key_prefix = generate_api_key()

    db.execute(
        text("""
            INSERT INTO api_keys (tenant_id, key_hash, key_prefix, display_name)
            VALUES (:tid, :hash, :prefix, :name)
        """),
        {"tid": tenant_id, "hash": key_hash,
         "prefix": key_prefix, "name": body.display_name},
    )
    db.commit()
    logger.info(f"API key created: {key_prefix} tenant={tenant_id}")
    return {
        "api_key":      raw_key,
        "key_prefix":   key_prefix,
        "display_name": body.display_name,
        "tenant_id":    tenant_id,
    }


@router.get("/keys")
def list_api_keys(
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
    clerk_user_id: str = None,
):
    _require_internal(request)
    cuid = x_clerk_user_id or clerk_user_id
    rows = db.execute(
        text("""
            SELECT k.id, k.key_prefix, k.display_name, k.is_active,
                   k.created_at, k.last_used_at, k.expires_at, k.tenant_id
            FROM api_keys k
            JOIN tenants t ON k.tenant_id = t.id::text
            JOIN users u ON t.owner_user_id = u.id
            WHERE u.clerk_user_id = :cuid
            ORDER BY k.created_at DESC
        """),
        {"cuid": cuid},
    ).fetchall()
    return [
        {
            "id":           str(r.id),
            "key_prefix":   r.key_prefix,
            "display_name": r.display_name,
            "is_active":    r.is_active,
            "created_at":   r.created_at.isoformat() if r.created_at else None,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "expires_at":   r.expires_at.isoformat() if r.expires_at else None,
            "tenant_id":    r.tenant_id,
        }
        for r in rows
    ]


@router.delete("/keys/{key_id}")
def revoke_api_key(
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    _require_internal(request)
    db.execute(
        text("UPDATE api_keys SET is_active = false WHERE id = :id"),
        {"id": key_id},
    )
    db.commit()
    return {"id": key_id, "revoked": True}


@router.get("/jobs")
def list_jobs(
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    _require_internal(request)
    rows = db.execute(
        text("""
            SELECT j.id, j.title, j.dialect, j.preset_id, j.status,
                   j.created_at, j.r2_key, j.callback_url, j.tenant_id
            FROM jobs j
            JOIN users u ON j.user_id = u.id
            WHERE u.clerk_user_id = :cuid
            ORDER BY j.created_at DESC
            LIMIT 50
        """),
        {"cuid": x_clerk_user_id},
    ).fetchall()
    return [
        {
            "id":           str(r.id),
            "title":        r.title,
            "dialect":      r.dialect,
            "preset":       r.preset_id,
            "status":       r.status.value if hasattr(r.status, "value") else str(r.status),
            "created_at":   r.created_at.isoformat() if r.created_at else None,
            "r2_key":       r.r2_key,
            "callback_url": r.callback_url,
            "tenant_id":    r.tenant_id,
        }
        for r in rows
    ]


@router.get("/webhooks")
def list_webhook_deliveries(
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    _require_internal(request)
    rows = db.execute(
        text("""
            SELECT w.id, w.job_id, w.callback_url, w.status,
                   w.attempts, w.next_retry_at, w.created_at, w.last_error
            FROM webhook_deliveries w
            JOIN tenants t ON w.tenant_id = t.id::text
            JOIN users u ON t.owner_user_id = u.id
            WHERE u.clerk_user_id = :cuid
            ORDER BY w.created_at DESC
            LIMIT 50
        """),
        {"cuid": x_clerk_user_id},
    ).fetchall()
    return [
        {
            "id":            str(r.id),
            "job_id":        r.job_id,
            "callback_url":  r.callback_url,
            "status":        r.status,
            "attempts":      r.attempts,
            "next_retry_at": r.next_retry_at.isoformat() if r.next_retry_at else None,
            "created_at":    r.created_at.isoformat() if r.created_at else None,
            "last_error":    r.last_error,
        }
        for r in rows
    ]
