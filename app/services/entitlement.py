"""
Entitlement Service
Tamil TTS Studio — VoxTN

Single source of truth for feature access.
Reads from user_subscriptions + subscription_plans in DB.
Used by routes and worker tasks to gate premium features.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Default free-tier flags (used when no subscription found)
FREE_FLAGS = {
    "voice_cloning":          False,
    "multi_speaker":          False,
    "advanced_presets":       False,
    "bulk_pdf":               False,
    "watermark":              True,
    "max_speakers":           1,
    "elevenlabs_monthly_chars": 0,
}


def get_user_flags(user_id: str, db: Session) -> dict:
    """
    Return feature_flags for a user based on their active subscription.
    Falls back to FREE_FLAGS if no active subscription found.
    """
    row = db.execute(
        text("""
            SELECT sp.feature_flags, sp.name, sp.is_beta,
                   sp.beta_expires_at, us.status,
                   us.current_period_end
            FROM user_subscriptions us
            JOIN subscription_plans sp ON sp.id = us.plan_id
            WHERE us.user_id = :user_id
              AND us.status IN ('active', 'trialing')
            ORDER BY us.created_at DESC
            LIMIT 1
        """),
        {"user_id": user_id},
    ).fetchone()

    if not row:
        logger.debug("entitlement: user_id=%s no active subscription — free tier", user_id)
        return {**FREE_FLAGS}

    flags = dict(row.feature_flags) if row.feature_flags else {**FREE_FLAGS}

    # Beta expiry check — downgrade to free if expired
    if row.is_beta and row.beta_expires_at:
        from datetime import datetime, timezone
        if datetime.now(timezone.utc) > row.beta_expires_at:
            logger.info(
                "entitlement: user_id=%s beta expired at %s — returning free flags",
                user_id, row.beta_expires_at,
            )
            return {**FREE_FLAGS}

    return flags


def can_use_voice_cloning(user_id: str, db: Session) -> bool:
    flags = get_user_flags(user_id, db)
    return bool(flags.get("voice_cloning", False))


def can_use_multi_speaker(user_id: str, db: Session) -> bool:
    flags = get_user_flags(user_id, db)
    return bool(flags.get("multi_speaker", False))


def needs_watermark(user_id: str, db: Session) -> bool:
    flags = get_user_flags(user_id, db)
    return bool(flags.get("watermark", True))


def get_max_speakers(user_id: str, db: Session) -> int:
    flags = get_user_flags(user_id, db)
    return int(flags.get("max_speakers", 1))


def get_elevenlabs_monthly_chars(user_id: str, db: Session) -> int:
    flags = get_user_flags(user_id, db)
    return int(flags.get("elevenlabs_monthly_chars", 0))


def can_use_advanced_presets(user_id: str, db: Session) -> bool:
    flags = get_user_flags(user_id, db)
    return bool(flags.get("advanced_presets", False))


def assert_voice_cloning(user_id: str, db: Session) -> None:
    """Raise HTTP 403 if user cannot use voice cloning."""
    from fastapi import HTTPException
    if not can_use_voice_cloning(user_id, db):
        raise HTTPException(
            status_code=403,
            detail="PREMIUM_REQUIRED: Voice cloning requires a Premium subscription."
        )


def assert_multi_speaker(user_id: str, db: Session) -> None:
    """Raise HTTP 403 if user cannot use multi-speaker mode."""
    from fastapi import HTTPException
    if not can_use_multi_speaker(user_id, db):
        raise HTTPException(
            status_code=403,
            detail="PREMIUM_REQUIRED: Multi-speaker mode requires a Premium subscription."
        )
