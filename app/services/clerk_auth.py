from __future__ import annotations
import httpx
import jwt as pyjwt
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

CLERK_JWKS_URL = "https://api.clerk.com/v1/jwks"
_jwks_cache: dict = {}


def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    try:
        resp = httpx.get(CLERK_JWKS_URL, timeout=5)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch Clerk JWKS: {e}")
        raise HTTPException(status_code=503, detail="Auth service unavailable")


def verify_clerk_token(token: str) -> dict:
    """Verify a Clerk session JWT. Returns decoded payload."""
    try:
        from jwt import PyJWKClient
        jwks_client = PyJWKClient(CLERK_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return payload
    except Exception as e:
        logger.warning(f"Clerk token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid session token")


def get_clerk_user_id(request: Request) -> str:
    """Extract and verify Clerk user ID from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = auth[7:]
    payload = verify_clerk_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no subject")
    return user_id


def get_or_create_user(clerk_user_id: str, email: str, db: Session) -> str:
    """Get existing user by clerk_user_id or create new one. Returns internal user UUID."""
    row = db.execute(
        text("SELECT id FROM users WHERE clerk_user_id = :cuid"),
        {"cuid": clerk_user_id},
    ).fetchone()
    if row:
        return str(row.id)

    # Try by email
    row = db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": email},
    ).fetchone()
    if row:
        db.execute(
            text("UPDATE users SET clerk_user_id = :cuid WHERE id = :id"),
            {"cuid": clerk_user_id, "id": str(row.id)},
        )
        db.commit()
        return str(row.id)

    # Create new user
    import uuid
    new_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO users (id, email, clerk_user_id, is_active, is_admin)
            VALUES (:id, :email, :cuid, true, false)
        """),
        {"id": new_id, "email": email, "cuid": clerk_user_id},
    )
    db.commit()
    logger.info(f"Created new user: {new_id} clerk={clerk_user_id}")
    return new_id
