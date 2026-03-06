"""
Voice Model Routes
Tamil TTS Studio — VoxTN
"""
import os
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Request, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.auth import get_current_user, validate_csrf
from app.services.entitlement import assert_voice_cloning
from app.services import elevenlabs as el

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voices", tags=["voices"])


def _assert_elevenlabs_configured():
    import os
    if not os.environ.get("ELEVENLABS_API_KEY", ""):
        raise HTTPException(
            status_code=503,
            detail="Voice cloning not configured. ELEVENLABS_API_KEY is not set."
        )

MIN_DURATION_S = 30
MAX_DURATION_S = 300
MAX_FILE_MB    = 50
ALLOWED_TYPES  = {"audio/wav", "audio/mpeg", "audio/mp3", "audio/x-wav"}


def _normalize_sample(input_path: str, output_path: str) -> float:
    import subprocess
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le",
        output_path
    ], check=True, capture_output=True)
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", output_path
    ], capture_output=True, text=True)
    return float(result.stdout.strip() or 0)


@router.post("/upload")
async def upload_voice(
    request:      Request,
    display_name: str        = Form(...),
    file:         UploadFile = File(...),
    csrf_token:   str        = Form(...),
    db:           Session    = Depends(get_db),
):
    # Auth: support both cookie session (legacy) and X-Internal-Secret (Next.js dashboard)
    from app.config import settings as app_settings
    internal_secret = request.headers.get("X-Internal-Secret", "")
    clerk_user_id   = request.headers.get("X-Clerk-User-Id", "")
    expected_secret = getattr(app_settings, "INTERNAL_API_SECRET", "")

    if internal_secret and expected_secret and internal_secret == expected_secret:
        # Server-to-server path — resolve user from clerk_user_id
        if not clerk_user_id:
            raise HTTPException(400, "X-Clerk-User-Id header required")
        user_row = db.execute(
            text("SELECT id, is_active FROM users WHERE clerk_user_id = :cuid"),
            {"cuid": clerk_user_id},
        ).fetchone()
        if not user_row:
            raise HTTPException(404, "User not found")

        class _UserProxy:
            def __init__(self, row):
                self.id        = str(row.id)
                self.is_active = row.is_active

        current_user = _UserProxy(user_row)
    else:
        # Cookie session path — legacy browser flow
        validate_csrf(request, csrf_token)
        current_user = get_current_user(request, db)

    _assert_elevenlabs_configured()
    assert_voice_cloning(current_user.id, db)

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {MAX_FILE_MB}MB limit")

    with tempfile.TemporaryDirectory() as tmpdir:
        suffix   = Path(file.filename).suffix or ".wav"
        raw_path  = os.path.join(tmpdir, f"sample_raw{suffix}")
        norm_path = os.path.join(tmpdir, "sample_normalized.wav")

        with open(raw_path, "wb") as f_out:
            f_out.write(content)

        try:
            duration = _normalize_sample(raw_path, norm_path)
        except Exception as e:
            logger.error("Voice normalization failed: %s", e)
            raise HTTPException(422, "Audio normalization failed.")

        if duration < MIN_DURATION_S:
            raise HTTPException(400, f"Sample too short: {duration:.1f}s (min {MIN_DURATION_S}s)")
        if duration > MAX_DURATION_S:
            raise HTTPException(400, f"Sample too long: {duration:.1f}s (max {MAX_DURATION_S}s)")

        # Create pending voice model record
        tenant_id = getattr(current_user, "tenant_id", None) or "default"
        row = db.execute(
            text("""
                INSERT INTO voice_models
                    (owner_user_id, display_name, status, tenant_id, created_at)
                VALUES (:uid, :name, 'pending', :tenant_id, :now)
                RETURNING id
            """),
            {"uid": current_user.id, "name": display_name,
             "tenant_id": tenant_id,
             "now": datetime.now(timezone.utc)},
        ).fetchone()
        db.commit()
        voice_model_id = str(row.id)

        # Upload normalized sample to R2 private bucket
        import boto3
        from botocore.config import Config as BotoConfig
        from app.config import settings as app_settings

        r2_key = f"voices/{current_user.id}/samples/{voice_model_id}/normalized.wav"
        try:
            r2_client = boto3.client(
                "s3",
                endpoint_url=f"https://{app_settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
                aws_access_key_id=app_settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=app_settings.R2_SECRET_ACCESS_KEY,
                config=BotoConfig(signature_version="s3v4"),
                region_name="auto",
            )
            r2_client.upload_file(
                norm_path,
                app_settings.R2_VOICE_SAMPLES_BUCKET,
                r2_key,
                ExtraArgs={"ContentType": "audio/wav"},
            )
            logger.info("Voice sample uploaded to R2: %s", r2_key)
        except Exception as e:
            logger.error("Voice sample R2 upload failed: %s", e)
            raise HTTPException(502, "Voice sample storage failed.")

        db.execute(
            text("UPDATE voice_models SET sample_r2_key = :key, status = 'processing' WHERE id = :id"),
            {"key": r2_key, "id": voice_model_id},
        )
        db.commit()

        # Provision on ElevenLabs
        tamil_ok = False
        try:
            result  = await el.upload_voice(display_name, norm_path)
            el_id   = result["voice_id"]
            test_p  = os.path.join(tmpdir, "tamil_test.mp3")
            tamil_ok = await el.test_tamil_support(el_id, test_p)

            db.execute(
                text("""
                    UPDATE voice_models
                    SET elevenlabs_voice_id = :el_id,
                        tamil_supported = :tamil,
                        status = 'active'
                    WHERE id = :id
                """),
                {"el_id": el_id, "tamil": tamil_ok, "id": voice_model_id},
            )
            db.commit()
            logger.info("Voice active: id=%s el_id=%s tamil=%s", voice_model_id, el_id, tamil_ok)

        except Exception as e:
            logger.error("ElevenLabs provisioning failed: %s", e)
            db.execute(
                text("UPDATE voice_models SET status = 'disabled' WHERE id = :id"),
                {"id": voice_model_id},
            )
            db.commit()
            raise HTTPException(502, "Voice provisioning failed. Please try again.")

    return {
        "voice_model_id":  voice_model_id,
        "display_name":    display_name,
        "status":          "active",
        "tamil_supported": tamil_ok,
    }



@router.get("/list")
def list_voices_internal(
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    """Server-to-server endpoint for Next.js dashboard. Uses X-Internal-Secret auth."""
    from app.config import settings as app_settings
    secret = request.headers.get("X-Internal-Secret", "")
    expected = getattr(app_settings, "INTERNAL_API_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not x_clerk_user_id:
        raise HTTPException(status_code=400, detail="X-Clerk-User-Id header required")

    # Resolve user from clerk_user_id
    user = db.execute(
        text("SELECT id FROM users WHERE clerk_user_id = :cuid"),
        {"cuid": x_clerk_user_id},
    ).fetchone()
    if not user:
        return []

    rows = db.execute(
        text("""
            SELECT id, display_name, status, tamil_supported,
                   is_public, created_at, disabled_at,
                   provider, monthly_char_limit, chars_used_this_month
            FROM voice_models
            WHERE owner_user_id = :uid
            ORDER BY created_at DESC
        """),
        {"uid": str(user.id)},
    ).fetchall()
    return [dict(r._mapping) for r in rows]

@router.get("/mine")
def list_my_voices(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    rows = db.execute(
        text("""
            SELECT id, display_name, status, tamil_supported,
                   is_public, created_at, disabled_at
            FROM voice_models
            WHERE owner_user_id = :uid
            ORDER BY created_at DESC
        """),
        {"uid": current_user.id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/{voice_id}")
def get_voice(voice_id: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    row = db.execute(
        text("""
            SELECT id, display_name, status, tamil_supported,
                   is_public, created_at, disabled_at
            FROM voice_models
            WHERE id = :id AND owner_user_id = :uid
        """),
        {"id": voice_id, "uid": current_user.id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Voice model not found")
    return dict(row._mapping)


@router.delete("/{voice_id}")
async def delete_voice(voice_id: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    row = db.execute(
        text("""
            SELECT id, elevenlabs_voice_id, sample_r2_key
            FROM voice_models WHERE id = :id AND owner_user_id = :uid
        """),
        {"id": voice_id, "uid": current_user.id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Voice model not found")

    now = datetime.now(timezone.utc)
    db.execute(
        text("UPDATE voice_models SET status = 'disabled', disabled_at = :now WHERE id = :id"),
        {"now": now, "id": voice_id},
    )
    db.execute(
        text("""
            UPDATE consent_authorizations
            SET status = 'revoked', revoked_at = :now
            WHERE voice_model_id = :vid AND status = 'approved'
        """),
        {"now": now, "vid": voice_id},
    )
    db.commit()

    if row.elevenlabs_voice_id:
        await el.delete_voice(row.elevenlabs_voice_id)

    return {"status": "deleted", "voice_model_id": voice_id}
