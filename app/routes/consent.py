"""
Consent Authorization Routes
Tamil TTS Studio — VoxTN
Token security: raw token never stored — SHA256 hash only.
"""
import hashlib
import secrets
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Header, APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voices/consent", tags=["consent"])

TOKEN_EXPIRY_HOURS = 72
CONSENT_VERSION    = "v1.0"


def _generate_token() -> tuple[str, str]:
    raw    = secrets.token_urlsafe(48)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _append_audit(db, consent_id: str, event: str, ip: str, actor_id: str = None):
    entry = json.dumps({
        "event":    event,
        "ts":       datetime.now(timezone.utc).isoformat(),
        "ip":       ip,
        "actor_id": actor_id,
    })
    db.execute(
        text("""
            UPDATE consent_authorizations
            SET audit_log = audit_log || :entry::jsonb
            WHERE id = :id
        """),
        {"entry": f"[{entry}]", "id": consent_id},
    )


class ConsentRequestBody(BaseModel):
    voice_model_id: str
    owner_user_id:  Optional[str] = None
    owner_email:    Optional[str] = None


class RevokeBody(BaseModel):
    reason: Optional[str] = None


# ── Dual-auth helper (cookie session OR X-Internal-Secret + X-Clerk-User-Id) ─
def _resolve_user(request: Request, db: Session):
    from app.config import settings as _settings
    internal_secret = request.headers.get("X-Internal-Secret", "")
    expected_secret = getattr(_settings, "INTERNAL_API_SECRET", "")
    clerk_user_id   = request.headers.get("X-Clerk-User-Id", "")
    if internal_secret and expected_secret and internal_secret == expected_secret:
        if not clerk_user_id:
            raise HTTPException(400, "X-Clerk-User-Id header required")
        from sqlalchemy import text as _text
        row = db.execute(
            _text("SELECT id, is_active FROM users WHERE clerk_user_id = :cuid"),
            {"cuid": clerk_user_id},
        ).fetchone()
        if not row:
            raise HTTPException(401, "User not found or not registered")
        class _Proxy:
            def __init__(self, r):
                self.id        = str(r.id)
                self.is_active = r.is_active
        return _Proxy(row)
    else:
        return get_current_user(request, db)


@router.post("/request")
def request_consent(
    body:    ConsentRequestBody,
    request: Request,
    db:      Session = Depends(get_db),
):
    current_user = _resolve_user(request, db)

    if not body.owner_user_id and not body.owner_email:
        raise HTTPException(400, "Provide owner_user_id or owner_email")

    vm = db.execute(
        text("SELECT id FROM voice_models WHERE id = :id AND status = 'active'"),
        {"id": body.voice_model_id},
    ).fetchone()
    if not vm:
        raise HTTPException(404, "Voice model not found or not active")

    existing = db.execute(
        text("""
            SELECT id, status FROM consent_authorizations
            WHERE voice_model_id = :vid
              AND requester_user_id = :rid
              AND status IN ('pending','approved')
        """),
        {"vid": body.voice_model_id, "rid": current_user.id},
    ).fetchone()
    if existing:
        return {"consent_id": str(existing.id), "status": existing.status,
                "message": "Consent already exists"}

    raw_token, token_hash = _generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    ip = request.client.host if request.client else "unknown"

    row = db.execute(
        text("""
            INSERT INTO consent_authorizations
                (voice_model_id, requester_user_id, owner_user_id, owner_email,
                 consent_token_hash, token_expires_at, consent_text_version,
                 status, ip_address, audit_log, created_at)
            VALUES
                (:vid, :rid, :oid, :oemail,
                 :token_hash, :expires, :version,
                 'pending', :ip, '[]', :now)
            RETURNING id
        """),
        {
            "vid": body.voice_model_id, "rid": current_user.id,
            "oid": body.owner_user_id,  "oemail": body.owner_email,
            "token_hash": token_hash,   "expires": expires_at,
            "version": CONSENT_VERSION, "ip": ip,
            "now": datetime.now(timezone.utc),
        },
    ).fetchone()
    db.commit()

    consent_id = str(row.id)
    _append_audit(db, consent_id, "consent_requested", ip, current_user.id)
    db.commit()

    logger.info("Consent requested: id=%s voice=%s", consent_id, body.voice_model_id)
    # TODO: send email with raw_token when email service wired
    # Link: https://tts.voxtn.online/consent/verify?token={raw_token}
    return {
        "consent_id": consent_id,
        "status":     "pending",
        "expires_at": expires_at.isoformat(),
    }


@router.get("/verify/{token}")
def verify_consent_token(token: str, db: Session = Depends(get_db)):
    token_hash = _hash_token(token)
    row = db.execute(
        text("""
            SELECT ca.id, ca.status, ca.token_expires_at,
                   ca.consent_text_version, ct.body_text,
                   vm.display_name as voice_name
            FROM consent_authorizations ca
            JOIN consent_texts ct ON ct.version = ca.consent_text_version
            JOIN voice_models vm  ON vm.id = ca.voice_model_id
            WHERE ca.consent_token_hash = :hash
        """),
        {"hash": token_hash},
    ).fetchone()

    if not row:
        raise HTTPException(404, "Token not found")
    if row.status != "pending":
        raise HTTPException(409, f"Consent already {row.status}")
    if datetime.now(timezone.utc) > row.token_expires_at:
        db.execute(
            text("UPDATE consent_authorizations SET status = 'expired' WHERE id = :id"),
            {"id": str(row.id)},
        )
        db.commit()
        raise HTTPException(410, "Token expired")

    return {
        "consent_id":   str(row.id),
        "voice_name":   row.voice_name,
        "consent_text": row.body_text,
        "version":      row.consent_text_version,
        "expires_at":   row.token_expires_at.isoformat(),
    }


@router.post("/approve/{token}")
def approve_consent(token: str, request: Request, db: Session = Depends(get_db)):
    token_hash = _hash_token(token)
    row = db.execute(
        text("""
            SELECT id, status, token_expires_at
            FROM consent_authorizations
            WHERE consent_token_hash = :hash
        """),
        {"hash": token_hash},
    ).fetchone()

    if not row:
        raise HTTPException(404, "Token not found")
    if row.status != "pending":
        raise HTTPException(409, f"Consent already {row.status}")
    if datetime.now(timezone.utc) > row.token_expires_at:
        raise HTTPException(410, "Token expired")

    ip  = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)

    db.execute(
        text("""
            UPDATE consent_authorizations
            SET status = 'approved', granted_at = :now, ip_address = :ip
            WHERE id = :id
        """),
        {"now": now, "ip": ip, "id": str(row.id)},
    )
    _append_audit(db, str(row.id), "consent_approved", ip)
    db.commit()

    logger.info("Consent approved: id=%s", row.id)
    return {"consent_id": str(row.id), "status": "approved",
            "granted_at": now.isoformat()}


@router.post("/revoke/{consent_id}")
def revoke_consent(
    consent_id: str,
    body:       RevokeBody,
    request:    Request,
    db:         Session = Depends(get_db),
):
    current_user = _resolve_user(request, db)

    row = db.execute(
        text("""
            SELECT ca.id, ca.status, vm.owner_user_id
            FROM consent_authorizations ca
            JOIN voice_models vm ON vm.id = ca.voice_model_id
            WHERE ca.id = :id
        """),
        {"id": consent_id},
    ).fetchone()

    if not row:
        raise HTTPException(404, "Consent not found")
    if str(row.owner_user_id) != str(current_user.id):
        raise HTTPException(403, "Only the voice owner can revoke consent")
    if row.status == "revoked":
        return {"status": "already_revoked"}

    ip  = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)

    db.execute(
        text("""
            UPDATE consent_authorizations
            SET status = 'revoked', revoked_at = :now
            WHERE id = :id
        """),
        {"now": now, "id": consent_id},
    )
    _append_audit(db, consent_id, "consent_revoked", ip, current_user.id)
    db.commit()

    logger.info("Consent revoked: id=%s by user=%s", consent_id, current_user.id)
    return {"consent_id": consent_id, "status": "revoked",
            "revoked_at": now.isoformat()}


@router.get("/mine")
def list_my_consents(request: Request, db: Session = Depends(get_db)):
    current_user = _resolve_user(request, db)
    rows = db.execute(
        text("""
            SELECT ca.id, ca.status, ca.granted_at, ca.revoked_at,
                   ca.created_at, vm.display_name as voice_name,
                   ca.consent_text_version
            FROM consent_authorizations ca
            JOIN voice_models vm ON vm.id = ca.voice_model_id
            WHERE ca.requester_user_id = :uid OR vm.owner_user_id = :uid
            ORDER BY ca.created_at DESC
        """),
        {"uid": current_user.id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]
