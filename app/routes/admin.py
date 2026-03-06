"""
Admin Control Plane
Tamil TTS Studio — VoxTN

Full internal admin API. Protected by get_admin_user (is_admin=True + valid JWT cookie).
All endpoints require browser login as an admin user OR a valid admin JWT cookie.

RBAC: get_admin_user() reuses existing JWT cookie auth + checks is_admin flag.
No separate secret header needed for browser-based access.
X-Admin-Secret header retained as fallback for CLI/curl operations.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.auth import get_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/../../admin", include_in_schema=False)
def admin_ui_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin")


# ── Auth helper ───────────────────────────────────────────────────────────────
def _get_admin(request: Request, db: Session) -> object:
    """
    Dual auth: accepts either:
    1. Valid JWT cookie with is_admin=True (browser-based)
    2. X-Admin-Secret header matching ADMIN_SECRET env var (CLI/curl)
    """
    secret   = os.environ.get("ADMIN_SECRET", "")
    provided = request.headers.get("X-Admin-Secret", "")
    if secret and provided == secret:
        return None  # CLI auth — no user object needed
    return get_admin_user(request, db)


# ── System Config ─────────────────────────────────────────────────────────────

def _get_config(db: Session, key: str) -> str:
    row = db.execute(
        text("SELECT value FROM system_config WHERE key = :key"),
        {"key": key},
    ).fetchone()
    return row.value if row else None


def _set_config(db: Session, key: str, value: str, admin_id: str = None):
    db.execute(text("""
        INSERT INTO system_config (key, value, updated_by, updated_at)
        VALUES (:key, :value, :uid, :now)
        ON CONFLICT (key) DO UPDATE SET
            value = EXCLUDED.value,
            updated_by = EXCLUDED.updated_by,
            updated_at = EXCLUDED.updated_at
    """), {"key": key, "value": value, "uid": admin_id,
           "now": datetime.now(timezone.utc)})
    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/users")
def list_users(
    request: Request,
    search:  Optional[str] = None,
    db:      Session = Depends(get_db),
):
    _get_admin(request, db)
    where = "WHERE u.email != 'cms@system.voxtn.internal'"
    params = {}
    if search:
        where += " AND (u.email ILIKE :search OR u.id::text ILIKE :search)"
        params["search"] = f"%{search}%"
    rows = db.execute(text(f"""
        SELECT u.id, u.email, u.is_active, u.is_admin,
               u.is_suspended, u.suspend_reason, u.created_at,
               sp.name as plan_name, us.status as sub_status
        FROM users u
        LEFT JOIN user_subscriptions us ON us.user_id = u.id
        LEFT JOIN subscription_plans sp ON sp.id = us.plan_id
        {where}
        ORDER BY u.created_at DESC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/users/{user_id}")
def get_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    _get_admin(request, db)
    row = db.execute(text("""
        SELECT u.id, u.email, u.is_active, u.is_admin,
               u.is_suspended, u.suspend_reason, u.suspended_at,
               u.stripe_customer_id, u.ghl_contact_id, u.created_at,
               sp.name as plan_name, us.status as sub_status,
               us.billing_cycle, us.current_period_end
        FROM users u
        LEFT JOIN user_subscriptions us ON us.user_id = u.id
        LEFT JOIN subscription_plans sp ON sp.id = us.plan_id
        WHERE u.id = :id
    """), {"id": user_id}).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    return dict(row._mapping)


class SetAdminBody(BaseModel):
    is_admin: bool

@router.post("/users/{user_id}/set-admin")
def set_admin_flag(
    user_id: str, body: SetAdminBody,
    request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    db.execute(text(
        "UPDATE users SET is_admin = :val WHERE id = :id"
    ), {"val": body.is_admin, "id": user_id})
    db.commit()
    return {"user_id": user_id, "is_admin": body.is_admin}


class SuspendBody(BaseModel):
    reason: Optional[str] = None

@router.post("/users/{user_id}/suspend")
def suspend_user(
    user_id: str, body: SuspendBody,
    request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    now = datetime.now(timezone.utc)
    db.execute(text("""
        UPDATE users SET
            is_suspended   = true,
            suspended_at   = :now,
            suspend_reason = :reason
        WHERE id = :id
    """), {"now": now, "reason": body.reason, "id": user_id})
    db.commit()
    logger.warning("Admin suspended user: %s reason=%s", user_id, body.reason)
    return {"user_id": user_id, "suspended": True, "reason": body.reason}


@router.post("/users/{user_id}/unsuspend")
def unsuspend_user(
    user_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    db.execute(text("""
        UPDATE users SET
            is_suspended = false, suspended_at = NULL,
            suspended_by = NULL,  suspend_reason = NULL
        WHERE id = :id
    """), {"id": user_id})
    db.commit()
    return {"user_id": user_id, "suspended": False}


class AssignPlanBody(BaseModel):
    plan_name:     str
    billing_cycle: Optional[str] = "none"

@router.post("/users/{user_id}/assign-plan")
def assign_plan(
    user_id: str, body: AssignPlanBody,
    request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    plan = db.execute(
        text("SELECT id FROM subscription_plans WHERE name = :n"),
        {"n": body.plan_name},
    ).fetchone()
    if not plan:
        raise HTTPException(404, f"Plan '{body.plan_name}' not found")
    now = datetime.now(timezone.utc)
    existing = db.execute(
        text("SELECT id FROM user_subscriptions WHERE user_id = :uid"),
        {"uid": user_id},
    ).fetchone()
    if existing:
        db.execute(text("""
            UPDATE user_subscriptions SET
                plan_id = :pid, status = 'active',
                billing_cycle = :cycle, cancelled_at = NULL, updated_at = :now
            WHERE user_id = :uid
        """), {"pid": str(plan.id), "cycle": body.billing_cycle,
               "now": now, "uid": user_id})
    else:
        db.execute(text("""
            INSERT INTO user_subscriptions
                (user_id, plan_id, status, billing_cycle, created_at, updated_at)
            VALUES (:uid, :pid, 'active', :cycle, :now, :now)
        """), {"uid": user_id, "pid": str(plan.id),
               "cycle": body.billing_cycle, "now": now})
    db.commit()
    return {"user_id": user_id, "plan": body.plan_name, "status": "active"}


@router.post("/users/{user_id}/revoke-plan")
def revoke_plan(
    user_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    free = db.execute(
        text("SELECT id FROM subscription_plans WHERE name = 'free'")
    ).fetchone()
    db.execute(text("""
        UPDATE user_subscriptions SET
            plan_id = :fid, status = 'active', billing_cycle = 'none',
            cancelled_at = :now, updated_at = :now
        WHERE user_id = :uid
    """), {"fid": str(free.id), "now": datetime.now(timezone.utc), "uid": user_id})
    db.commit()
    return {"user_id": user_id, "plan": "free"}


@router.get("/users/{user_id}/usage")
def user_usage(
    user_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    rows = db.execute(text("""
        SELECT chars_tts_total, chars_elevenlabs, jobs_created,
               jobs_elevenlabs, abuse_flag, abuse_reason,
               period_start, period_end
        FROM usage_tracking WHERE user_id = :uid
        ORDER BY period_start DESC LIMIT 10
    """), {"uid": user_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/users/{user_id}/voice-usage")
def user_voice_usage(
    user_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    rows = db.execute(text("""
        SELECT job_id, voice_model_id, character_count,
               provider, created_at
        FROM voice_usage_log WHERE user_id = :uid
        ORDER BY created_at DESC LIMIT 50
    """), {"uid": user_id}).fetchall()
    return [dict(r._mapping) for r in rows]


class AbuseFlagBody(BaseModel):
    abuse_flag:   bool
    abuse_reason: Optional[str] = None

@router.post("/users/{user_id}/abuse-flag")
def set_abuse_flag(
    user_id: str, body: AbuseFlagBody,
    request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    db.execute(text("""
        UPDATE usage_tracking SET
            abuse_flag = :flag, abuse_reason = :reason,
            updated_at = :now
        WHERE user_id = :uid
          AND period_end > now()
    """), {"flag": body.abuse_flag, "reason": body.abuse_reason,
           "now": datetime.now(timezone.utc), "uid": user_id})
    db.commit()
    return {"user_id": user_id, "abuse_flag": body.abuse_flag}


@router.get("/users/{user_id}/entitlements")
def user_entitlements(
    user_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    from app.services.entitlement import get_user_flags
    flags = get_user_flags(user_id, db)
    plan = db.execute(text("""
        SELECT sp.name, us.status, us.billing_cycle
        FROM user_subscriptions us
        JOIN subscription_plans sp ON sp.id = us.plan_id
        WHERE us.user_id = :uid AND us.status = 'active'
    """), {"uid": user_id}).fetchone()
    return {
        "user_id": user_id,
        "plan":    plan.name if plan else "free",
        "flags":   flags,
    }


# ══════════════════════════════════════════════════════════════════════════════
# VOICE MODELS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/voices")
def list_voices(request: Request, db: Session = Depends(get_db)):
    _get_admin(request, db)
    rows = db.execute(text("""
        SELECT vm.id, vm.display_name, vm.status, vm.tamil_supported,
               vm.elevenlabs_voice_id, vm.created_at, vm.disabled_at,
               u.email as owner_email
        FROM voice_models vm
        JOIN users u ON u.id = vm.owner_user_id
        ORDER BY vm.created_at DESC
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/voices/{voice_id}/disable")
def disable_voice(
    voice_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    now = datetime.now(timezone.utc)
    db.execute(text("""
        UPDATE voice_models SET status = 'disabled', disabled_at = :now
        WHERE id = :id
    """), {"now": now, "id": voice_id})
    db.execute(text("""
        UPDATE consent_authorizations SET status = 'revoked', revoked_at = :now
        WHERE voice_model_id = :vid AND status = 'approved'
    """), {"now": now, "vid": voice_id})
    db.commit()
    return {"voice_id": voice_id, "status": "disabled"}


@router.post("/voices/{voice_id}/enable")
def enable_voice(
    voice_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    db.execute(text(
        "UPDATE voice_models SET status = 'active', disabled_at = NULL WHERE id = :id"
    ), {"id": voice_id})
    db.commit()
    return {"voice_id": voice_id, "status": "active"}


@router.get("/voices/{voice_id}/declaration")
def voice_declaration(
    voice_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    row = db.execute(text("""
        SELECT vod.*, u.email as owner_email
        FROM voice_ownership_declarations vod
        JOIN users u ON u.id = vod.user_id
        WHERE vod.voice_model_id = :vid
        ORDER BY vod.declared_at DESC LIMIT 1
    """), {"vid": voice_id}).fetchone()
    if not row:
        raise HTTPException(404, "No declaration found")
    return dict(row._mapping)


@router.get("/voices/{voice_id}/consents")
def voice_consents(
    voice_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    rows = db.execute(text("""
        SELECT ca.id, ca.status, ca.granted_at, ca.revoked_at,
               ca.created_at, ca.consent_text_version, ca.ip_address,
               u.email as requester_email
        FROM consent_authorizations ca
        JOIN users u ON u.id = ca.requester_user_id
        WHERE ca.voice_model_id = :vid
        ORDER BY ca.created_at DESC
    """), {"vid": voice_id}).fetchall()
    return [dict(r._mapping) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# CONSENT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/consents")
def list_consents(
    request: Request,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _get_admin(request, db)
    where = ""
    params = {}
    if status_filter:
        where = "WHERE ca.status = :status"
        params["status"] = status_filter
    rows = db.execute(text(f"""
        SELECT ca.id, ca.status, ca.granted_at, ca.revoked_at,
               ca.created_at, ca.consent_text_version, ca.ip_address,
               vm.display_name as voice_name,
               req.email as requester_email,
               own.email as owner_email
        FROM consent_authorizations ca
        JOIN voice_models vm ON vm.id = ca.voice_model_id
        JOIN users req ON req.id = ca.requester_user_id
        LEFT JOIN users own ON own.id = ca.owner_user_id
        {where}
        ORDER BY ca.created_at DESC
        LIMIT 200
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/consents/{consent_id}/audit-log")
def consent_audit_log(
    consent_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    row = db.execute(text(
        "SELECT audit_log FROM consent_authorizations WHERE id = :id"
    ), {"id": consent_id}).fetchone()
    if not row:
        raise HTTPException(404, "Consent not found")
    return {"consent_id": consent_id, "audit_log": row.audit_log}


@router.post("/consents/{consent_id}/force-revoke")
def force_revoke_consent(
    consent_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    import json
    now = datetime.now(timezone.utc)
    entry = json.dumps({
        "event": "admin_force_revoked",
        "ts": now.isoformat(),
        "ip": request.client.host if request.client else "admin",
    })
    db.execute(text("""
        UPDATE consent_authorizations SET
            status = 'revoked', revoked_at = :now,
            audit_log = audit_log || :entry::jsonb
        WHERE id = :id
    """), {"now": now, "entry": f"[{entry}]", "id": consent_id})
    db.commit()
    return {"consent_id": consent_id, "status": "revoked"}


@router.post("/consents/{consent_id}/force-expire")
def force_expire_consent(
    consent_id: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    db.execute(text(
        "UPDATE consent_authorizations SET status = 'expired' WHERE id = :id"
    ), {"id": consent_id})
    db.commit()
    return {"consent_id": consent_id, "status": "expired"}


# ══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION PLANS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/plans")
def list_plans(request: Request, db: Session = Depends(get_db)):
    _get_admin(request, db)
    rows = db.execute(text("""
        SELECT id, name, display_name, is_active, is_beta,
               monthly_price_cad, annual_price_cad,
               feature_flags, beta_expires_at, beta_max_users
        FROM subscription_plans ORDER BY monthly_price_cad
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


class UpdatePlanBody(BaseModel):
    display_name:       Optional[str]   = None
    monthly_price_cad:  Optional[float] = None
    annual_price_cad:   Optional[float] = None
    is_active:          Optional[bool]  = None
    beta_expires_at:    Optional[str]   = None
    beta_max_users:     Optional[int]   = None
    feature_flags:      Optional[dict]  = None

@router.patch("/plans/{plan_name}")
def update_plan(
    plan_name: str, body: UpdatePlanBody,
    request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    import json
    updates = {}
    if body.display_name      is not None: updates["display_name"]      = body.display_name
    if body.monthly_price_cad is not None: updates["monthly_price_cad"] = body.monthly_price_cad
    if body.annual_price_cad  is not None: updates["annual_price_cad"]  = body.annual_price_cad
    if body.is_active         is not None: updates["is_active"]         = body.is_active
    if body.beta_expires_at   is not None: updates["beta_expires_at"]   = body.beta_expires_at
    if body.beta_max_users    is not None: updates["beta_max_users"]    = body.beta_max_users
    if body.feature_flags     is not None: updates["feature_flags"]     = json.dumps(body.feature_flags)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc)
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["name"] = plan_name
    db.execute(text(f"UPDATE subscription_plans SET {set_clause} WHERE name = :name"), updates)
    db.commit()
    return {"plan": plan_name, "updated": list(updates.keys())}


# ══════════════════════════════════════════════════════════════════════════════
# COUPONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/coupons")
def list_coupons(request: Request, db: Session = Depends(get_db)):
    _get_admin(request, db)
    rows = db.execute(text("""
        SELECT c.id, c.code, c.discount_type, c.discount_value,
               c.is_active, c.is_beta, c.valid_from, c.valid_until,
               c.max_redemptions, c.max_per_user,
               COUNT(cr.id) as redemption_count
        FROM coupons c
        LEFT JOIN coupon_redemptions cr ON cr.coupon_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


class CreateCouponBody(BaseModel):
    code:           str
    description:    Optional[str]   = None
    discount_type:  str             # 'percent' or 'fixed'
    discount_value: float
    applies_to:     Optional[str]   = "both"
    max_redemptions: Optional[int]  = None
    max_per_user:   Optional[int]   = 1
    valid_from:     Optional[str]   = None
    valid_until:    Optional[str]   = None
    is_beta:        Optional[bool]  = False
    plan_name:      Optional[str]   = None

@router.post("/coupons")
def create_coupon(
    body: CreateCouponBody,
    request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    plan_id = None
    if body.plan_name:
        p = db.execute(
            text("SELECT id FROM subscription_plans WHERE name = :n"),
            {"n": body.plan_name},
        ).fetchone()
        if p:
            plan_id = str(p.id)
    now = datetime.now(timezone.utc)
    db.execute(text("""
        INSERT INTO coupons
            (code, description, discount_type, discount_value, applies_to,
             max_redemptions, max_per_user, valid_from, valid_until,
             is_beta, plan_id, is_active, created_at)
        VALUES
            (:code, :desc, :dtype, :dval, :applies,
             :max_r, :max_u, :vfrom, :vuntil,
             :is_beta, :plan_id, true, :now)
    """), {
        "code": body.code.upper(), "desc": body.description,
        "dtype": body.discount_type, "dval": body.discount_value,
        "applies": body.applies_to, "max_r": body.max_redemptions,
        "max_u": body.max_per_user,
        "vfrom": body.valid_from or now.isoformat(),
        "vuntil": body.valid_until,
        "is_beta": body.is_beta, "plan_id": plan_id, "now": now,
    })
    db.commit()
    return {"code": body.code.upper(), "status": "created"}


@router.delete("/coupons/{code}")
def deactivate_coupon(
    code: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    db.execute(text(
        "UPDATE coupons SET is_active = false WHERE code = :code"
    ), {"code": code.upper()})
    db.commit()
    return {"code": code.upper(), "is_active": False}


@router.get("/coupons/{code}/redemptions")
def coupon_redemptions(
    code: str, request: Request, db: Session = Depends(get_db),
):
    _get_admin(request, db)
    rows = db.execute(text("""
        SELECT cr.redeemed_at, cr.discount_applied, u.email
        FROM coupon_redemptions cr
        JOIN coupons c ON c.id = cr.coupon_id
        JOIN users u ON u.id = cr.user_id
        WHERE c.code = :code
        ORDER BY cr.redeemed_at DESC
    """), {"code": code.upper()}).fetchall()
    return [dict(r._mapping) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM CONTROLS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/system/config")
def get_system_config(request: Request, db: Session = Depends(get_db)):
    _get_admin(request, db)
    rows = db.execute(text(
        "SELECT key, value, description, updated_at FROM system_config ORDER BY key"
    )).fetchall()
    return [dict(r._mapping) for r in rows]


class SetConfigBody(BaseModel):
    value: str

@router.post("/system/config/{key}")
def set_system_config(
    key: str, body: SetConfigBody,
    request: Request, db: Session = Depends(get_db),
):
    admin = _get_admin(request, db)
    admin_id = str(admin.id) if admin else None
    _set_config(db, key, body.value, admin_id)
    logger.info("System config updated: key=%s value=%s by=%s", key, body.value, admin_id)
    return {"key": key, "value": body.value}


@router.post("/system/maintenance")
def set_maintenance(
    request: Request,
    body: SetConfigBody,
    db: Session = Depends(get_db),
):
    """Toggle maintenance mode. value = 'true' or 'false'."""
    admin = _get_admin(request, db)
    admin_id = str(admin.id) if admin else None
    _set_config(db, "maintenance_mode", body.value, admin_id)
    return {"maintenance_mode": body.value}


@router.post("/system/elevenlabs-toggle")
def toggle_elevenlabs(
    request: Request,
    body: SetConfigBody,
    db: Session = Depends(get_db),
):
    """Kill switch for ElevenLabs. value = 'true' or 'false'."""
    admin = _get_admin(request, db)
    admin_id = str(admin.id) if admin else None
    _set_config(db, "elevenlabs_enabled", body.value, admin_id)
    logger.warning("ElevenLabs toggle: enabled=%s by=%s", body.value, admin_id)
    return {"elevenlabs_enabled": body.value}


# ══════════════════════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/metrics")
def get_metrics(request: Request, db: Session = Depends(get_db)):
    _get_admin(request, db)
    from app.services.concurrency_guard import check_status

    # Jobs per day (last 7 days)
    jobs_daily = db.execute(text("""
        SELECT DATE(created_at AT TIME ZONE 'UTC') as day,
               COUNT(*) as total,
               COUNT(*) FILTER (WHERE status = 'done')   as done,
               COUNT(*) FILTER (WHERE status = 'failed') as failed
        FROM jobs
        WHERE created_at > now() - INTERVAL '7 days'
        GROUP BY day ORDER BY day DESC
    """)).fetchall()

    # Average processing duration (done jobs last 7 days)
    avg_duration = db.execute(text("""
        SELECT ROUND(AVG(EXTRACT(EPOCH FROM (updated_at - created_at))), 2) as avg_seconds
        FROM jobs
        WHERE status = 'done'
          AND created_at > now() - INTERVAL '7 days'
    """)).fetchone()

    # ElevenLabs usage totals (rolling)
    el_usage = db.execute(text("""
        SELECT SUM(chars_elevenlabs) as total_el_chars,
               SUM(jobs_elevenlabs)  as total_el_jobs
        FROM usage_tracking
        WHERE period_start > now() - INTERVAL '30 days'
    """)).fetchone()

    # Active abuse flags
    abuse_count = db.execute(text(
        "SELECT COUNT(*) as cnt FROM usage_tracking WHERE abuse_flag = true"
    )).fetchone()

    # Total users
    user_count = db.execute(text(
        "SELECT COUNT(*) as cnt FROM users WHERE email != 'cms@system.voxtn.internal'"
    )).fetchone()

    # Users per plan
    plan_dist = db.execute(text("""
        SELECT sp.name, COUNT(us.id) as user_count
        FROM user_subscriptions us
        JOIN subscription_plans sp ON sp.id = us.plan_id
        WHERE us.status = 'active'
        GROUP BY sp.name
    """)).fetchall()

    concurrency = check_status()

    return {
        "jobs_daily":        [dict(r._mapping) for r in jobs_daily],
        "avg_duration_secs": avg_duration.avg_seconds if avg_duration else None,
        "elevenlabs": {
            "total_chars_30d": el_usage.total_el_chars or 0,
            "total_jobs_30d":  el_usage.total_el_jobs  or 0,
        },
        "abuse_flags_active": abuse_count.cnt,
        "total_users":        user_count.cnt,
        "plan_distribution":  [dict(r._mapping) for r in plan_dist],
        "concurrency":        concurrency,
        "system_config": {
            "maintenance_mode":   _get_config(db, "maintenance_mode"),
            "elevenlabs_enabled": _get_config(db, "elevenlabs_enabled"),
            "concurrency_cap":    _get_config(db, "concurrency_cap"),
        },
    }

@router.post("/maintenance/cleanup-active-tasks")
def cleanup_active_tasks(request: Request, db: Session = Depends(get_db)):
    _get_admin(request, db)
    from sqlalchemy import text as sql_text
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    result = db.execute(sql_text(
        "DELETE FROM active_tasks WHERE started_at < :cutoff"
    ), {"cutoff": cutoff})
    db.commit()
    return {"deleted": result.rowcount, "cutoff": cutoff.isoformat()}
