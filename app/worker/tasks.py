"""
Celery tasks for TTS job processing.
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
from app.worker.tts import synthesize_chunk
from app.worker.audio import stitch_chunks
from app.config import settings

logger = structlog.get_logger()


def get_job_dir(job_id: str) -> str:
    d = os.path.join(settings.OUTPUT_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


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
    db = self.db
    log = logger.bind(job_id=job_id)

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        log.error("job_not_found")
        return

    try:
        # Mark processing
        job.status = JobStatus.PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        log.info("job_started", voice=job.voice_mode, speed=job.speed)

        job_dir = get_job_dir(job_id)

        # --- Chunking ---
        chunks_text = make_chunks(job.original_text)
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

        # --- Synthesize each chunk ---
        chunk_audio_paths = []
        for chunk in chunk_records:
            chunk_log = log.bind(chunk_index=chunk.chunk_index)
            chunk_log.info("chunk_synthesis_start", text_len=len(chunk.text))

            chunk_output = os.path.join(job_dir, f"chunk_{chunk.chunk_index:04d}.mp3")
            try:
                audio_bytes = synthesize_chunk(
                    text=chunk.text,
                    voice_mode=job.voice_mode,
                    speed=job.speed,
                    max_retries=2,
                )
                with open(chunk_output, "wb") as f:
                    f.write(audio_bytes)

                chunk.status = ChunkStatus.DONE
                chunk.output_path = chunk_output
                chunk.attempts += 1
                db.commit()

                chunk_audio_paths.append(chunk_output)
                chunk_log.info("chunk_synthesis_done", bytes=len(audio_bytes))

            except Exception as e:
                chunk.status = ChunkStatus.FAILED
                chunk.error_message = str(e)[:500]
                chunk.attempts += 1
                db.commit()
                chunk_log.error("chunk_synthesis_failed", error=str(e))
                raise RuntimeError(
                    f"Chunk {chunk.chunk_index} failed: {e}"
                ) from e

        # --- Stitch ---
        final_mp3 = os.path.join(job_dir, "output.mp3")
        log.info("stitching_start", chunk_count=len(chunk_audio_paths))
        stitch_chunks(chunk_audio_paths, final_mp3)
        log.info("stitching_done", output=final_mp3)

        # --- Cleanup chunk files if not keeping ---
        if not settings.KEEP_CHUNK_FILES:
            for path in chunk_audio_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

        # --- Mark done ---
        job.status = JobStatus.DONE
        job.output_path = final_mp3
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        log.info("job_done", output=final_mp3)

    except Exception as e:
        log.error("job_failed", error=str(e))
        job.status = JobStatus.FAILED
        job.error_message = str(e)[:1000]
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
