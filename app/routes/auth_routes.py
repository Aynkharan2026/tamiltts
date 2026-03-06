from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.auth import verify_password, create_access_token, generate_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password"},
            status_code=401,
        )
    if not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Account is disabled"},
            status_code=403,
        )

    token = create_access_token(user.id)
    csrf = generate_csrf_token()
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400,
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf,
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response

@router.get("/api/me")
async def get_me(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user(request, db)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "id":       user.id,
        "email":    user.email,
        "is_admin": user.is_admin,
    }

@router.get("/api/subscription")
async def get_subscription(request: Request, db: Session = Depends(get_db)):
    from sqlalchemy import text as sql_text
    try:
        user = get_current_user(request, db)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = db.execute(sql_text("""
        SELECT sp.name, sp.feature_flags, us.status,
               us.current_period_end, sp.is_beta, sp.beta_expires_at
        FROM user_subscriptions us
        JOIN subscription_plans sp ON sp.id = us.plan_id
        WHERE us.user_id = :uid AND us.status IN ('active','trialing')
        ORDER BY us.created_at DESC LIMIT 1
    """), {"uid": user.id}).fetchone()
    if not row:
        return {"plan": "free", "status": "none", "feature_flags": {
            "voice_cloning": False, "multi_speaker": False,
            "advanced_presets": False, "watermark": True,
            "max_speakers": 1, "elevenlabs_monthly_chars": 0
        }}
    return {
        "plan":              row.name,
        "status":            row.status,
        "feature_flags":     row.feature_flags,
        "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "is_beta":           row.is_beta,
        "beta_expires_at":   row.beta_expires_at.isoformat() if row.beta_expires_at else None,
    }


@router.get("/api/entitlements")
async def get_entitlements(request: Request, db: Session = Depends(get_db)):
    from app.services.entitlement import get_user_flags
    try:
        user = get_current_user(request, db)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")
    flags = get_user_flags(user.id, db)
    return {"user_id": user.id, "flags": flags}
