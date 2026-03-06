"""
Celery tasks for TTS job processing.
Phase 3A additions:
  - Unicode sanitizer on all text before chunking
  - Concurrency guard (acquire/release via Redis)
  - Watermark append at FFmpeg concat stage (free tier only)
  - Usage tracking increment per job
"""

import os
import logging
import structlog
from datetime import datetime, timezone
from celery import Task
from app.worker.celery_app import celery_app
from app.database import SessionLocal
from app.models import Job, JobChunk, JobStatus, ChunkStatus, VoiceMode
from app.worker.chunker import make_chunks
from app.worker.tts import synthesize_chunk, synthesize_chunk_coqui
from app.worker.audio import stitch_chunks
from app.config import settings
from app.services.unicode_sanitizer import sanitize
from app.services.concurrency_guard import acquire, release, TASK_WEIGHTS
from app.services.entitlement import needs_watermark

logger = structlog.get_logger()

# Pre-generated watermark asset paths
WATERMARK_MP3   = os.path.join(settings.OUTPUT_DIR, "_assets", "watermark.mp3")
SILENCE_400_MP3 = os.path.join(settings.OUTPUT_DIR, "_assets", "silence_400ms.mp3")


def get_job_dir(job_id: str) -> str:
    d = os.path.join(settings.OUTPUT_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


def _increment_usage(db, user_id: str, char_count: int, provider: str):
    """
    Increment usage_tracking for the current rolling 7-day window.
    Creates a new window record if none exists for today.
    Never raises — usage tracking failure must not fail a job.
    """
    try:
        from sqlalchemy import text
        from datetime import timedelta
        now   = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = start + timedelta(days=7)

        existing = db.execute(
            text("""
                SELECT id FROM usage_tracking
                WHERE user_id = :uid AND period_start = :start
            """),
            {"uid": user_id, "start": start},
        ).fetchone()

        if existing:
            el_inc  = char_count if provider == "elevenlabs" else 0
            el_jobs = 1 if provider == "elevenlabs" else 0
            db.execute(
                text("""
                    UPDATE usage_tracking SET
                        chars_tts_total  = chars_tts_total  + :chars,
                        chars_elevenlabs = chars_elevenlabs + :el_chars,
                        jobs_created     = jobs_created     + 1,
                        jobs_elevenlabs  = jobs_elevenlabs  + :el_jobs,
                        updated_at       = :now
                    WHERE user_id = :uid AND period_start = :start
                """),
                {"chars": char_count, "el_chars": el_inc, "el_jobs": el_jobs,
                 "now": now, "uid": user_id, "start": start},
            )
        else:
            el_chars = char_count if provider == "elevenlabs" else 0
            el_jobs  = 1 if provider == "elevenlabs" else 0
            db.execute(
                text("""
                    INSERT INTO usage_tracking
                        (user_id, period_start, period_end,
                         chars_tts_total, chars_elevenlabs,
                         jobs_created, jobs_elevenlabs,
                         created_at, updated_at)
                    VALUES
                        (:uid, :start, :end,
                         :chars, :el_chars,
                         1, :el_jobs,
                         :now, :now)
                """),
                {"uid": user_id, "start": start, "end": end,
                 "chars": char_count, "el_chars": el_chars,
                 "el_jobs": el_jobs, "now": now},
            )
        db.commit()
    except Exception as e:
        logger.warning("usage_tracking_failed", error=str(e), user_id=user_id)


def _log_voice_usage(db, job_id: str, user_id: str, char_count: int, provider: str):
    """Append a row to voice_usage_log. Never raises."""
    try:
        from sqlalchemy import text
        db.execute(
            text("""
                INSERT INTO voice_usage_log
                    (job_id, user_id, character_count, provider, created_at)
                VALUES
                    (:job_id, :uid, :chars, :provider, :now)
            """),
            {"job_id": job_id, "uid": user_id, "chars": char_count,
             "provider": provider, "now": datetime.now(timezone.utc)},
        )
        db.commit()
    except Exception as e:
        logger.warning("voice_usage_log_failed", error=str(e))


def _append_watermark(main_mp3: str, output_mp3: str) -> bool:
    """
    Append silence_400ms + watermark to main audio via ffmpeg concat.
    Single encode pass — does not re-encode main audio.
    Returns True on success, False on failure (caller continues without watermark).
    """
    import subprocess
    if not os.path.exists(WATERMARK_MP3) or not os.path.exists(SILENCE_400_MP3):
        logger.warning("watermark_assets_missing", watermark=WATERMARK_MP3,
                       silence=SILENCE_400_MP3)
        return False
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-i", main_mp3,
            "-i", SILENCE_400_MP3,
            "-i", WATERMARK_MP3,
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map", "[out]",
            "-c:a", "libmp3lame", "-q:a", "4",
            output_mp3,
        ], check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error("watermark_append_failed", error=str(e))
        return False


class DBTask(Task):
    """Base task that provides a DB session."""
    _db = None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(
    bind=True,
    base=DBTask,
    name="app.worker.tasks.process_tts_job",
    max_retries=0,
    acks_late=True,
)
def process_tts_job(self, job_id: str):
    db      = self.db
    log     = logger.bind(job_id=job_id)
    task_id = self.request.id or job_id
    acquired = False

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        log.error("job_not_found")
        return

    try:
        # --- Concurrency guard: acquire slot ---
        acquired = acquire("tts", task_id, str(job.user_id), job_id, db)
        if not acquired:
            log.warning("concurrency_limit_reached — requeueing")
            # Requeue with 30s countdown
            raise self.retry(countdown=30, max_retries=5)

        # --- Mark processing ---
        job.status     = JobStatus.PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        log.info("job_started", voice=job.voice_mode, speed=job.speed)

        job_dir = get_job_dir(job_id)

        # --- Unicode sanitizer ---
        raw_text       = job.original_text
        sanitized_text = sanitize(raw_text, source="standard_job")
        log.info("sanitizer_done",
                 original_len=len(raw_text),
                 sanitized_len=len(sanitized_text))

        # --- Chunking ---
        chunks_text = make_chunks(sanitized_text)
        log.info("chunks_created", count=len(chunks_text))

        # Persist chunks (clear existing in case of re-run)
        db.query(JobChunk).filter(JobChunk.job_id == job_id).delete()
        db.commit()

        chunk_records = []
        for idx, text in enumerate(chunks_text):
            chunk = JobChunk(
                job_id=job_id,
                chunk_index=idx,
                text=text,
                status=ChunkStatus.PENDING,
            )
            db.add(chunk)
            chunk_records.append(chunk)
        db.commit()

        # --- Resolve preset + voice params ---
        from sqlalchemy import text as sql_text
        from app.worker.tts import get_voice_name, build_rate_str, build_pitch_str, build_volume_str

        preset_row = None
        if job.preset_id:
            preset_row = db.execute(
                sql_text("""
                    SELECT preset_key, pitch_percent, rate_percent, volume_percent
                    FROM tts_presets WHERE preset_key = :key AND is_active = true
                """),
                {"key": job.preset_id},
            ).fetchone()

        pitch_pct  = preset_row.pitch_percent  if preset_row else 0
        rate_pct   = preset_row.rate_percent   if preset_row else 0
        volume_pct = preset_row.volume_percent if preset_row else 0

        # Resolve voice name from dialect + voice_mode (gender encoded in voice_mode)
        # voice_mode is either a raw Edge-TTS name or a legacy enum value
        voice_mode_str = str(job.voice_mode) if job.voice_mode else "ta-LK-SaranyaNeural"

        # Detect if it's a direct Edge-TTS voice name (contains "Neural")
        if "Neural" in voice_mode_str:
            resolved_voice = voice_mode_str
            # infer gender from voice name
            gender = "male" if any(
                m in voice_mode_str for m in ["Kumar", "Valluvar", "Surya", "Anbu"]
            ) else "female"
        else:
            # Legacy enum — map to dialect-aware voice
            dialect = getattr(job, "dialect", None) or "ta-LK"
            gender  = "male" if "male" in voice_mode_str.lower() else "female"
            resolved_voice = get_voice_name(dialect, gender)

        rate_str   = build_rate_str(job.speed or 1.0, rate_pct)
        pitch_str  = build_pitch_str(pitch_pct)
        volume_str = build_volume_str(volume_pct)

        log.info("voice_resolved",
                 voice=resolved_voice, rate=rate_str,
                 pitch=pitch_str, volume=volume_str,
                 preset=job.preset_id)

        # --- Synthesize each chunk ---
        chunk_audio_paths = []
        total_chars       = 0
        for chunk in chunk_records:
            chunk_log = log.bind(chunk_index=chunk.chunk_index)
            chunk_log.info("chunk_synthesis_start", text_len=len(chunk.text))

            chunk_output = os.path.join(job_dir, f"chunk_{chunk.chunk_index:04d}.mp3")
            try:
                # ââ Provider dispatch (Phase 9) ââââââââââââââââ
                if provider == 'coqui':
                    audio_bytes = synthesize_chunk_coqui(
                        text=chunk.text,
                        voice_model_path=str(getattr(job, 'voice_model_id', '')),
                        language=getattr(job, 'dialect', 'ta') or 'ta',
                        pitch=pitch_pct,
                        rate=1.0 + (rate_pct / 100),
                        volume=1.0 + (volume_pct / 100),
                        coqui_inference_url=settings.COQUI_INFERENCE_URL,
                        internal_secret=settings.INTERNAL_API_SECRET,
                    )
                else:
                    audio_bytes = synthesize_chunk(
                        text=chunk.text,
                        voice_name=resolved_voice,
                        rate_str=rate_str,
                        pitch_str=pitch_str,
                        volume_str=volume_str,
                        max_retries=2,
                    )
                with open(chunk_output, "wb") as f:
                    f.write(audio_bytes)

                chunk.status      = ChunkStatus.DONE
                chunk.output_path = chunk_output
                chunk.attempts   += 1
                db.commit()

                chunk_audio_paths.append(chunk_output)
                total_chars += len(chunk.text)
                chunk_log.info("chunk_synthesis_done", bytes=len(audio_bytes))

            except Exception as e:
                chunk.status        = ChunkStatus.FAILED
                chunk.error_message = str(e)[:500]
                chunk.attempts     += 1
                db.commit()
                chunk_log.error("chunk_synthesis_failed", error=str(e))
                raise RuntimeError(f"Chunk {chunk.chunk_index} failed: {e}") from e

        # --- Stitch ---
        stitched_mp3 = os.path.join(job_dir, "stitched.mp3")
        log.info("stitching_start", chunk_count=len(chunk_audio_paths))
        stitch_chunks(chunk_audio_paths, stitched_mp3)
        log.info("stitching_done", output=stitched_mp3)

        # --- Cleanup chunk files ---
        if not settings.KEEP_CHUNK_FILES:
            for path in chunk_audio_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

        # --- Watermark (free tier only) ---
        final_mp3 = os.path.join(job_dir, "output.mp3")

        # --- Resolve provider (Phase 6) ---
        try:
            provider_info = _resolve_tts_provider(job, db)
        except PermissionError as pe:
            raise RuntimeError(str(pe)) from pe
        provider = provider_info["provider"]

        apply_wm = needs_watermark(str(job.user_id), db)
        if apply_wm:
            log.info("watermark_applying")
            wm_ok = _append_watermark(stitched_mp3, final_mp3)
            if wm_ok:
                log.info("watermark_applied")
                try:
                    os.remove(stitched_mp3)
                except OSError:
                    pass
            else:
                # Watermark failed — use stitched output without watermark
                log.warning("watermark_failed_using_plain_output")
                os.rename(stitched_mp3, final_mp3)
        else:
            # Premium/Beta — no watermark
            os.rename(stitched_mp3, final_mp3)
            log.info("watermark_skipped_premium")

        # --- Usage tracking ---
        _increment_usage(db, str(job.user_id), total_chars, provider)
        _log_voice_usage(db, job_id, str(job.user_id), total_chars, provider)

        # --- ElevenLabs char cap increment ---
        if provider == "elevenlabs":
            voice_model_id = getattr(job, "voice_model_id", None)
            if voice_model_id:
                _increment_el_chars(db, str(voice_model_id), total_chars)

        # --- R2 Upload ---
        r2_key = None
        try:
            from app.services.r2_storage import R2StorageService
            r2 = R2StorageService()
            filename = f"{job_id}.mp3"
            tenant_id = getattr(job, "tenant_id", None) or "default"
            r2_key = r2.upload_mp3(final_mp3, job_id, filename, tenant_id)
            log.info("r2_upload_done", r2_key=r2_key)
        except Exception as e:
            log.warning("r2_upload_failed", error=str(e))
            r2_key = None
        # --- Mark done ---
        completed_at = datetime.now(timezone.utc)
        job.status      = JobStatus.DONE
        job.output_path = final_mp3
        if r2_key:
            job.r2_key = r2_key
        job.updated_at  = completed_at
        db.commit()
        log.info("job_done", output=final_mp3, chars=total_chars,
                 watermarked=apply_wm)

        # --- Patch Sanity ---
        _patch_sanity_job(getattr(job, "sanity_id", None), {
            "status":      "done",
            "r2Key":       r2_key or "",
            "engine":      provider,
            "completedAt": completed_at.isoformat(),
        })

    except Exception as e:
        log.error("job_failed", error=str(e))
        failed_at = datetime.now(timezone.utc)
        job.status        = JobStatus.FAILED
        job.error_message = str(e)[:1000]
        job.updated_at    = failed_at
        db.commit()

        # --- Patch Sanity ---
        _patch_sanity_job(getattr(job, "sanity_id", None), {
            "status": "failed",
            "error":  str(e)[:500],
        })

    finally:
        # Always release concurrency slot
        if acquired:
            release("tts", task_id, db)
            log.info("concurrency_slot_released")


@celery_app.task(name="app.worker.tasks.retry_pending_webhooks")
def retry_pending_webhooks():
    """Celery beat task: retry pending webhook deliveries every 5 minutes."""
    from app.services.webhook_dispatch import retry_pending_webhooks as _retry
    db = SessionLocal()
    try:
        count = _retry(db)
        return {"retried": count}
    finally:
        db.close()


def _dispatch_callback(job_id: str, tenant_id: str, callback_url: str, db):
    """Fire outbound webhook after job completion. Never raises."""
    try:
        from app.services.r2_storage import R2StorageService
        from app.services.webhook_dispatch import dispatch_webhook
        r2 = R2StorageService()
        signed = r2.generate_signed_url(job_id + ".mp3")
        payload = {
            "job_id":       job_id,
            "status":       "done",
            "audio_url":    signed.get("url", ""),
            "tenant_id":    tenant_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        dispatch_webhook(db, job_id, tenant_id, callback_url, payload)
    except Exception as e:
        logger.warning(f"Callback dispatch failed: job={job_id} error={e}")



def _resolve_tts_provider(job, db) -> dict:
    """
    Resolve the TTS provider for a job.
    Returns dict with keys: provider, voice_name, el_voice_id
    Blueprint Section 5.3 engine resolution order.
    """
    from sqlalchemy import text as sql_text

    voice_model_id = getattr(job, "voice_model_id", None)

    if voice_model_id:
        # Check consent status
        consent = db.execute(
            sql_text("""
                SELECT ca.status, vm.tamil_supported, vm.elevenlabs_voice_id,
                       vm.status as vm_status, vm.chars_used_this_month,
                       vm.monthly_char_limit
                FROM consent_authorizations ca
                JOIN voice_models vm ON vm.id = ca.voice_model_id
                WHERE ca.voice_model_id = :vmid
                  AND ca.requester_user_id = :uid
                  AND ca.status = 'approved'
                LIMIT 1
            """),
            {"vmid": voice_model_id, "uid": str(job.user_id)},
        ).fetchone()

        if not consent:
            raise PermissionError("CONSENT_REQUIRED")

        if consent.vm_status != "active":
            raise PermissionError("VOICE_MODEL_DISABLED")

        # -- Coqui check (Phase 9) -- runs before ElevenLabs --------------
        from app.config import settings as _s
        import urllib.request as _ur
        def _coqui_healthy():
            try:
                with _ur.urlopen(
                    f"{_s.COQUI_INFERENCE_URL}/health", timeout=2
                ) as r: return r.status == 200
            except Exception: return False
        if _coqui_healthy():
            return {
                "provider":    "coqui",
                "el_voice_id": None,
            }
        # -- ElevenLabs (fallback if Coqui unreachable) --------------------
        if consent.tamil_supported and consent.elevenlabs_voice_id:
            # Check monthly char cap
            if consent.chars_used_this_month >= consent.monthly_char_limit:
                logger.warning(
                    "elevenlabs_char_cap_hit voice_model=%s — falling back to edge_tts",
                    voice_model_id,
                )
            else:
                return {
                    "provider":    "elevenlabs",
                    "el_voice_id": consent.elevenlabs_voice_id,
                }

        # tamil_supported=False or cap hit — fall back to Edge-TTS with warning
        logger.warning(
            "voice_model_tamil_unsupported voice_model=%s — using Edge-TTS fallback",
            voice_model_id,
        )

    # Default: Edge-TTS
    return {"provider": "edge_tts", "el_voice_id": None}


def _increment_el_chars(db, voice_model_id: str, char_count: int):
    """Increment ElevenLabs character usage counter on voice model."""
    from sqlalchemy import text as sql_text
    try:
        db.execute(
            sql_text("""
                UPDATE voice_models
                SET chars_used_this_month = chars_used_this_month + :n
                WHERE id = :id
            """),
            {"n": char_count, "id": voice_model_id},
        )
        db.commit()
    except Exception as e:
        logger.warning("el_char_increment_failed voice_model=%s error=%s", voice_model_id, e)


def _patch_sanity_job(sanity_id: str, patch: dict):
    """Patch a Sanity job document after worker completion. Never raises."""
    if not sanity_id:
        return
    if not settings.SANITY_API_TOKEN or not settings.SANITY_PROJECT_ID:
        logger.warning("sanity_patch_skipped_no_config")
        return
    try:
        import urllib.request as _urllib
        import json as _json
        url = (
            f"https://{settings.SANITY_PROJECT_ID}.api.sanity.io/v2021-06-07"
            f"/data/mutate/{settings.SANITY_DATASET}"
        )
        mutations = [{"patch": {"id": sanity_id, "set": patch}}]
        body = _json.dumps({"mutations": mutations}).encode()
        req = _urllib.Request(
            url, data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.SANITY_API_TOKEN}",
            },
            method="POST",
        )
        with _urllib.urlopen(req, timeout=10) as resp:
            logger.info(f"sanity_patch_done sanity_id={sanity_id} http={resp.status}")
    except Exception as e:
        logger.warning(f"sanity_patch_failed sanity_id={sanity_id} error={e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 7 — Multi-Speaker Conversation Worker
# ═══════════════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.worker.tasks.process_conversation_job", bind=True, max_retries=2)
def process_conversation_job(self, conversation_id: str):
    """
    Process a multi-speaker conversation job.
    1. Load conversation + speakers + segments from DB
    2. Synthesize each segment with assigned speaker voice
    3. Stitch all segments into one MP3
    4. Upload to R2
    5. Update conversation_jobs status to done
    """
    import os
    import tempfile
    import structlog
    from datetime import datetime, timezone
    from sqlalchemy import text as sql_text
    from app.database import SessionLocal
    from app.worker.tts import synthesize_chunk, build_rate_str, build_pitch_str, build_volume_str
    from app.worker.audio import stitch_chunks

    log = structlog.get_logger().bind(conversation_id=conversation_id)
    log.info("conversation_job_start")

    db = SessionLocal()
    try:
        # ── Load conversation ─────────────────────────────────────────────────
        conv = db.execute(
            sql_text("""
                SELECT id, user_id, tenant_id, status, speaker_count
                FROM conversation_jobs WHERE id = :id
            """),
            {"id": conversation_id},
        ).fetchone()

        if not conv:
            log.error("conversation_not_found")
            return

        if conv.status != "queued":
            log.warning("conversation_not_queued", status=conv.status)
            return

        # Mark processing
        db.execute(
            sql_text("UPDATE conversation_jobs SET status = 'processing', updated_at = :now WHERE id = :id"),
            {"now": datetime.now(timezone.utc), "id": conversation_id},
        )
        db.commit()

        # ── Load speakers ─────────────────────────────────────────────────────
        speaker_rows = db.execute(
            sql_text("""
                SELECT speaker_index, edge_tts_voice, voice_model_id,
                       preset_key, pitch_offset, rate_modifier, volume_db
                FROM conversation_speakers
                WHERE conversation_id = :id
                ORDER BY speaker_index
            """),
            {"id": conversation_id},
        ).fetchall()

        # Build speaker lookup by index
        speakers = {}
        for sp in speaker_rows:
            speakers[sp.speaker_index] = sp

        # ── Load segments ─────────────────────────────────────────────────────
        segments = db.execute(
            sql_text("""
                SELECT id, sequence_order, speaker_index, text, char_count
                FROM conversation_segments
                WHERE conversation_id = :id
                ORDER BY sequence_order
            """),
            {"id": conversation_id},
        ).fetchall()

        if not segments:
            raise RuntimeError("No segments found for conversation")

        # ── Synthesize each segment ───────────────────────────────────────────
        segment_audio_paths = []
        total_chars = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            for seg in segments:
                sp = speakers.get(seg.speaker_index)
                if not sp:
                    raise RuntimeError(f"No speaker found for index {seg.speaker_index}")

                # Resolve voice
                voice_name = sp.edge_tts_voice or "ta-LK-SaranyaNeural"

                # Build rate/pitch/volume from speaker modifiers
                rate_str   = build_rate_str(sp.rate_modifier or 1.0, 0)
                pitch_str  = build_pitch_str(int(sp.pitch_offset or 0))
                volume_str = build_volume_str(int(sp.volume_db or 0))

                seg_path = os.path.join(tmpdir, f"seg_{seg.sequence_order:04d}.mp3")
                seg_log  = log.bind(seq=seg.sequence_order, speaker=seg.speaker_index)
                seg_log.info("segment_synthesis_start", chars=seg.char_count)

                try:
                    audio_bytes = synthesize_chunk(
                        text=seg.text,
                        voice_name=voice_name,
                        rate_str=rate_str,
                        pitch_str=pitch_str,
                        volume_str=volume_str,
                        max_retries=2,
                    )
                    with open(seg_path, "wb") as f:
                        f.write(audio_bytes)

                    # Update segment status
                    db.execute(
                        sql_text("""
                            UPDATE conversation_segments
                            SET status = 'done', segment_r2_key = NULL
                            WHERE id = :id
                        """),
                        {"id": str(seg.id)},
                    )
                    db.commit()

                    segment_audio_paths.append(seg_path)
                    total_chars += seg.char_count
                    seg_log.info("segment_synthesis_done", bytes=len(audio_bytes))

                except Exception as e:
                    db.execute(
                        sql_text("UPDATE conversation_segments SET status = 'failed' WHERE id = :id"),
                        {"id": str(seg.id)},
                    )
                    db.commit()
                    raise RuntimeError(f"Segment {seg.sequence_order} failed: {e}") from e

            # ── Stitch ────────────────────────────────────────────────────────
            stitched_path = os.path.join(tmpdir, "conversation.mp3")
            log.info("conversation_stitch_start", segments=len(segment_audio_paths))
            stitch_chunks(segment_audio_paths, stitched_path, silence_ms=600)
            log.info("conversation_stitch_done")

            # ── Upload to R2 ──────────────────────────────────────────────────
            r2_key = None
            try:
                from app.services.r2_storage import R2StorageService
                r2 = R2StorageService()
                tenant_id = conv.tenant_id or "default"
                filename  = f"{conversation_id}.mp3"
                r2_key    = r2.upload_mp3(stitched_path, conversation_id, filename, tenant_id)
                log.info("conversation_r2_upload_done", r2_key=r2_key)
            except Exception as e:
                log.warning("conversation_r2_upload_failed", error=str(e))

            # ── Mark done ─────────────────────────────────────────────────────
            db.execute(
                sql_text("""
                    UPDATE conversation_jobs
                    SET status = 'done', output_r2_key = :r2_key, updated_at = :now
                    WHERE id = :id
                """),
                {"r2_key": r2_key, "now": datetime.now(timezone.utc), "id": conversation_id},
            )
            db.commit()

            # ── Usage tracking ────────────────────────────────────────────────
            _increment_usage(db, str(conv.user_id), total_chars, "edge_tts")
            _log_voice_usage(db, conversation_id, str(conv.user_id), total_chars, "edge_tts")

            log.info("conversation_job_done", total_chars=total_chars, r2_key=r2_key)

    except Exception as e:
        log.error("conversation_job_failed", error=str(e))
        try:
            db.execute(
                sql_text("""
                    UPDATE conversation_jobs
                    SET status = 'failed', error_message = :err, updated_at = :now
                    WHERE id = :id
                """),
                {"err": str(e)[:500], "now": datetime.now(timezone.utc), "id": conversation_id},
            )
            db.commit()
        except Exception:
            pass
        raise self.retry(exc=e, countdown=30)
    finally:
        db.close()
