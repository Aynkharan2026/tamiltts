from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_hash, key_prefix)."""
    raw    = "vtn_" + secrets.token_urlsafe(32)
    hashed = _hash_key(raw)
    prefix = raw[:12]
    return raw, hashed, prefix


def validate_api_key(request: Request, db: Session) -> dict:
    raw = request.headers.get("X-API-Key", "")
    if not raw:
        raise HTTPException(status_code=401, detail="API key required")
    key_hash = _hash_key(raw)
    row = db.execute(
        text("""
            SELECT id, tenant_id, display_name, is_active, expires_at
            FROM api_keys
            WHERE key_hash = :hash
        """),
        {"hash": key_hash},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not row.is_active:
        raise HTTPException(status_code=401, detail="API key inactive")
    if row.expires_at and row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API key expired")
    db.execute(
        text("UPDATE api_keys SET last_used_at = NOW() WHERE key_hash = :hash"),
        {"hash": key_hash},
    )
    db.commit()
    return {"tenant_id": row.tenant_id, "display_name": row.display_name}
