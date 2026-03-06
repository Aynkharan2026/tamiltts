from __future__ import annotations
import hashlib
import hmac
import json
import logging
import uuid
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import Depends
from app.database import get_db
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Clerk Sync"])


def _verify_svix(payload: bytes, svix_id: str, svix_ts: str, svix_sig: str, secret: str) -> bool:
    """Verify Svix webhook signature."""
    try:
        base = f"{svix_id}.{svix_ts}.{payload.decode()}"
        key = secret.replace("whsec_", "")
        import base64
        key_bytes = base64.b64decode(key)
        sig = hmac.new(key_bytes, base.encode(), hashlib.sha256).digest()
        expected = "v1," + base64.b64encode(sig).decode()
        return any(s.strip() == expected for s in svix_sig.split(" "))
    except Exception as e:
        logger.warning(f"Svix verification error: {e}")
        return False


@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    db: Session = Depends(get_db),
    svix_id: str = Header(None, alias="svix-id"),
    svix_timestamp: str = Header(None, alias="svix-timestamp"),
    svix_signature: str = Header(None, alias="svix-signature"),
):
    body = await request.body()
    secret = getattr(settings, "CLERK_WEBHOOK_SECRET", "")

    if secret and svix_id and svix_timestamp and svix_signature:
        if not _verify_svix(body, svix_id, svix_timestamp, svix_signature, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = json.loads(body)
    event_type = event.get("type", "")
    data = event.get("data", {})

    logger.info(f"Clerk webhook: {event_type}")

    if event_type == "user.created":
        _sync_user(data, db)
    elif event_type == "user.updated":
        _sync_user(data, db)
    elif event_type == "user.deleted":
        _deactivate_user(data, db)
    elif event_type == "organization.created":
        _sync_org(data, db)

    return {"status": "ok"}


def _sync_user(data: dict, db: Session):
    clerk_id = data.get("id", "")
    emails = data.get("email_addresses", [])
    email = emails[0].get("email_address", "") if emails else ""
    first_name = data.get("first_name") or ""
    last_name = data.get("last_name") or ""

    if not clerk_id or not email:
        return

    existing = db.execute(
        text("SELECT id FROM users WHERE clerk_user_id = :cuid OR email = :email"),
        {"cuid": clerk_id, "email": email},
    ).fetchone()

    if existing:
        db.execute(
            text("""
                UPDATE users
                SET clerk_user_id = :cuid,
                    email = :email,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {"cuid": clerk_id, "email": email, "id": str(existing.id)},
        )
    else:
        new_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO users (id, email, clerk_user_id, is_active, is_admin)
                VALUES (:id, :email, :cuid, true, false)
                ON CONFLICT (email) DO UPDATE
                SET clerk_user_id = EXCLUDED.clerk_user_id,
                    updated_at = NOW()
            """),
            {"id": new_id, "email": email, "cuid": clerk_id},
        )
    db.commit()
    logger.info(f"Synced user: {email} clerk={clerk_id}")


def _deactivate_user(data: dict, db: Session):
    clerk_id = data.get("id", "")
    if not clerk_id:
        return
    db.execute(
        text("UPDATE users SET is_active = false WHERE clerk_user_id = :cuid"),
        {"cuid": clerk_id},
    )
    db.commit()
    logger.info(f"Deactivated user: clerk={clerk_id}")


def _sync_org(data: dict, db: Session):
    clerk_org_id = data.get("id", "")
    name = data.get("name", "")
    slug = data.get("slug", clerk_org_id[:50])

    if not clerk_org_id:
        return

    existing = db.execute(
        text("SELECT id FROM tenants WHERE clerk_org_id = :oid OR slug = :slug"),
        {"oid": clerk_org_id, "slug": slug},
    ).fetchone()

    if existing:
        db.execute(
            text("""
                UPDATE tenants
                SET clerk_org_id = :oid, name = :name, updated_at = NOW()
                WHERE id = :id
            """),
            {"oid": clerk_org_id, "name": name, "id": str(existing.id)},
        )
    else:
        # Find owner from Clerk org memberships — use a placeholder for now
        new_id = str(uuid.uuid4())
        placeholder_user = db.execute(
            text("SELECT id FROM users WHERE email = 'hello@voxtn.com' LIMIT 1")
        ).fetchone()
        owner_id = str(placeholder_user.id) if placeholder_user else None
        if owner_id:
            db.execute(
                text("""
                    INSERT INTO tenants (id, name, slug, owner_user_id, clerk_org_id, is_active)
                    VALUES (:id, :name, :slug, :owner, :oid, true)
                    ON CONFLICT (slug) DO UPDATE
                    SET clerk_org_id = EXCLUDED.clerk_org_id,
                        updated_at = NOW()
                """),
                {"id": new_id, "name": name, "slug": slug,
                 "owner": owner_id, "oid": clerk_org_id},
            )
            db.commit()
    logger.info(f"Synced org: {name} clerk={clerk_org_id}")
