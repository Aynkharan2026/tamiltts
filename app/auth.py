import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session
from app.config import settings
from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_current_user(request: Request, db: Session) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    # Suspended users are blocked with 403 (not redirected — clear message)
    if getattr(user, "is_suspended", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Contact support@voxtn.com.",
        )
    return user


def get_admin_user(request: Request, db: Session) -> User:
    """Require authenticated user with is_admin=True. Used by all admin routes."""
    user = get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


# ── CSRF double-submit protection ──────────────────────────────────────────
import secrets as _secrets

def generate_csrf_token() -> str:
    return _secrets.token_hex(32)

def validate_csrf(request: "Request", form_token: str) -> None:
    from fastapi import HTTPException
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token or not form_token or cookie_token != form_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

