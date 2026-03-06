"""
Conversation Routes — Phase 7
Tamil TTS Studio — VoxTN
Multi-speaker conversation job API.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Header, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["conversations"])


# ── Auth helper ───────────────────────────────────────────────────────────────

def _resolve_user(request: Request, db: Session, clerk_user_id: str | None) -> dict:
    """
    Dual auth: X-Internal-Secret + X-Clerk-User-Id (Next.js dashboard)
    or cookie session (legacy browser).
    Returns dict with keys: id, tenant_id
    """
    internal_secret  = request.headers.get("X-Internal-Secret", "")
    expected_secret  = getattr(settings, "INTERNAL_API_SECRET", "")

    if internal_secret and expected_secret and internal_secret == expected_secret:
        if not clerk_user_id:
            raise HTTPException(400, "X-Clerk-User-Id header required")
        row = db.execute(
            text("SELECT id, tenant_id FROM users WHERE clerk_user_id = :cuid"),
            {"cuid": clerk_user_id},
        ).fetchone()
        if not row:
            raise HTTPException(401, "User not found or not registered")
        return {"id": str(row.id), "tenant_id": row.tenant_id or "default"}
    else:
        from app.auth import get_current_user
        user = get_current_user(request, db)
        return {"id": str(user.id), "tenant_id": getattr(user, "tenant_id", None) or "default"}


# ── POST /api/conversations ───────────────────────────────────────────────────

@router.post("")
async def create_conversation(
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    """
    Create a conversation job.
    Body (JSON):
    {
        "input_mode": "markup" | "structured",
        "text": "<S1>Hello</S1><S2>Hi</S2>",   # markup mode
        "segments": [                             # structured mode
            {"speaker_index": 0, "text": "Hello"},
            {"speaker_index": 1, "text": "Hi"}
        ],
        "speakers": [
            {
                "speaker_index": 0,
                "label": "Speaker A",
                "edge_tts_voice": "ta-LK-SaranyaNeural",
                "preset_key": null,
                "pitch_offset": 0,
                "rate_modifier": 1.0,
                "volume_db": 0.0
            }
        ]
    }
    """
    user = _resolve_user(request, db, x_clerk_user_id)
    body = await request.json()

    input_mode = body.get("input_mode", "structured")
    if input_mode not in ("markup", "structured"):
        raise HTTPException(400, "input_mode must be 'markup' or 'structured'")

    speakers = body.get("speakers", [])
    if not speakers or len(speakers) < 1 or len(speakers) > 5:
        raise HTTPException(400, "Between 1 and 5 speakers required")

    # Parse segments
    if input_mode == "structured":
        segments = body.get("segments", [])
        if not segments:
            raise HTTPException(400, "segments required for structured mode")
    else:
        # markup mode — parse <S0>...</S0> tags
        import re
        raw_text = body.get("text", "")
        if not raw_text:
            raise HTTPException(400, "text required for markup mode")
        matches = re.findall(r"<S(\d)>(.*?)</S\1>", raw_text, re.DOTALL)
        if not matches:
            raise HTTPException(400, "No valid <SN>...</SN> tags found in text")
        segments = [
            {"speaker_index": int(m[0]), "text": m[1].strip()}
            for m in matches
        ]

    if not segments:
        raise HTTPException(400, "No segments parsed from input")

    total_chars   = sum(len(s["text"]) for s in segments)
    speaker_count = len(speakers)
    now           = datetime.now(timezone.utc)

    # Insert conversation job
    conv_row = db.execute(
        text("""
            INSERT INTO conversation_jobs
                (user_id, tenant_id, input_mode, speaker_count, total_chars, status, created_at, updated_at)
            VALUES (:uid, :tenant_id, :input_mode, :speaker_count, :total_chars, 'queued', :now, :now)
            RETURNING id
        """),
        {
            "uid":           user["id"],
            "tenant_id":     user["tenant_id"],
            "input_mode":    input_mode,
            "speaker_count": speaker_count,
            "total_chars":   total_chars,
            "now":           now,
        },
    ).fetchone()
    conv_id = str(conv_row.id)

    # Insert speakers
    for sp in speakers:
        db.execute(
            text("""
                INSERT INTO conversation_speakers
                    (conversation_id, speaker_index, label, voice_model_id,
                     edge_tts_voice, preset_key, pitch_offset, rate_modifier, volume_db)
                VALUES (:conv_id, :idx, :label, :vm_id,
                        :edge_voice, :preset_key, :pitch, :rate, :vol)
            """),
            {
                "conv_id":    conv_id,
                "idx":        sp.get("speaker_index", 0),
                "label":      sp.get("label", f"Speaker {sp.get('speaker_index', 0)}"),
                "vm_id":      sp.get("voice_model_id"),
                "edge_voice": sp.get("edge_tts_voice"),
                "preset_key": sp.get("preset_key"),
                "pitch":      sp.get("pitch_offset", 0),
                "rate":       sp.get("rate_modifier", 1.0),
                "vol":        sp.get("volume_db", 0.0),
            },
        )

    # Insert segments
    for i, seg in enumerate(segments):
        char_count = len(seg["text"])
        db.execute(
            text("""
                INSERT INTO conversation_segments
                    (conversation_id, speaker_index, sequence_order, text, char_count, status, created_at)
                VALUES (:conv_id, :sp_idx, :seq, :text, :chars, 'pending', :now)
            """),
            {
                "conv_id": conv_id,
                "sp_idx":  seg.get("speaker_index", 0),
                "seq":     i,
                "text":    seg["text"],
                "chars":   char_count,
                "now":     now,
            },
        )

    db.commit()

    # Dispatch Celery task
    try:
        from app.worker.celery_app import celery_app
        celery_app.send_task(
            "app.worker.tasks.process_conversation_job",
            args=[conv_id],
        )
        logger.info("conversation_dispatched conv_id=%s", conv_id)
    except Exception as e:
        logger.warning("conversation_dispatch_failed conv_id=%s error=%s", conv_id, e)

    logger.info("conversation_created conv_id=%s user=%s segments=%d", conv_id, user["id"], len(segments))

    return {
        "conversation_id": conv_id,
        "status":          "queued",
        "input_mode":      input_mode,
        "speaker_count":   speaker_count,
        "segment_count":   len(segments),
        "total_chars":     total_chars,
    }


# ── GET /api/conversations ────────────────────────────────────────────────────

@router.get("")
def list_conversations(
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    user = _resolve_user(request, db, x_clerk_user_id)
    rows = db.execute(
        text("""
            SELECT id, input_mode, speaker_count, total_chars,
                   status, output_r2_key, created_at, updated_at
            FROM conversation_jobs
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"uid": user["id"]},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


# ── GET /api/conversations/{id} ───────────────────────────────────────────────

@router.get("/{conv_id}")
def get_conversation(
    conv_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    user = _resolve_user(request, db, x_clerk_user_id)
    conv = db.execute(
        text("""
            SELECT id, input_mode, speaker_count, total_chars,
                   status, output_r2_key, error_message, created_at, updated_at
            FROM conversation_jobs
            WHERE id = :id AND user_id = :uid
        """),
        {"id": conv_id, "uid": user["id"]},
    ).fetchone()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    speakers = db.execute(
        text("""
            SELECT speaker_index, label, edge_tts_voice, preset_key,
                   pitch_offset, rate_modifier, volume_db
            FROM conversation_speakers
            WHERE conversation_id = :id
            ORDER BY speaker_index
        """),
        {"id": conv_id},
    ).fetchall()

    segments = db.execute(
        text("""
            SELECT sequence_order, speaker_index, text, char_count,
                   status, duration_ms, segment_r2_key
            FROM conversation_segments
            WHERE conversation_id = :id
            ORDER BY sequence_order
        """),
        {"id": conv_id},
    ).fetchall()

    return {
        **dict(conv._mapping),
        "speakers": [dict(r._mapping) for r in speakers],
        "segments": [dict(r._mapping) for r in segments],
    }


# ── DELETE /api/conversations/{id} ───────────────────────────────────────────

@router.delete("/{conv_id}")
def delete_conversation(
    conv_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    user = _resolve_user(request, db, x_clerk_user_id)
    conv = db.execute(
        text("SELECT id, status FROM conversation_jobs WHERE id = :id AND user_id = :uid"),
        {"id": conv_id, "uid": user["id"]},
    ).fetchone()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.status == "processing":
        raise HTTPException(409, "Cannot delete a conversation currently being processed")

    db.execute(
        text("DELETE FROM conversation_jobs WHERE id = :id"),
        {"id": conv_id},
    )
    db.commit()
    logger.info("conversation_deleted conv_id=%s user=%s", conv_id, user["id"])
    return {"deleted": conv_id}

# ── GET /api/conversations/{id}/download ─────────────────────────────────────

@router.get("/{conv_id}/download")
def download_conversation(
    conv_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_clerk_user_id: str = Header(None, alias="X-Clerk-User-Id"),
):
    """Return a signed R2 URL for the stitched conversation MP3."""
    user = _resolve_user(request, db, x_clerk_user_id)
    conv = db.execute(
        text("""
            SELECT id, status, output_r2_key
            FROM conversation_jobs
            WHERE id = :id AND user_id = :uid
        """),
        {"id": conv_id, "uid": user["id"]},
    ).fetchone()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.status != "done":
        raise HTTPException(409, f"Conversation is not ready (status: {conv.status})")
    if not conv.output_r2_key:
        raise HTTPException(404, "Audio not available")

    try:
        from app.services.r2_storage import R2StorageService
        r2     = R2StorageService()
        signed = r2.generate_signed_url(conv.output_r2_key)
        from fastapi.responses import RedirectResponse
        return RedirectResponse(signed["url"], status_code=302)
    except Exception as e:
        logger.error("conversation_download_failed conv_id=%s error=%s", conv_id, e)
        raise HTTPException(500, "Failed to generate download URL")
