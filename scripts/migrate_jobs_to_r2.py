#!/usr/bin/env python3
"""
Migrate legacy jobs (r2_key IS NULL) from local disk to Cloudflare R2.
Idempotent — safe to run multiple times.

Usage:
    cd /opt/tamiltts-saas/app && source venv/bin/activate
    python scripts/migrate_jobs_to_r2.py
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_r2")

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)

def main():
    from app.services.r2_storage import R2StorageService
    r2 = R2StorageService()

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, output_path, user_id
            FROM jobs
            WHERE r2_key IS NULL
              AND status = 'done'
              AND output_path IS NOT NULL
            ORDER BY created_at ASC
        """)).fetchall()

    log.info("Found %d legacy jobs to migrate", len(rows))
    migrated = skipped = failed = 0

    for row in rows:
        job_id = str(row.id)
        output_path = row.output_path

        if not output_path or not os.path.exists(output_path):
            log.warning("SKIP %s — file missing: %s", job_id, output_path)
            skipped += 1
            continue

        try:
            filename = f"{job_id}.mp3"
            tenant_id = "default"
            r2_key = r2.upload_mp3(output_path, job_id, filename, tenant_id)

            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE jobs SET r2_key = :key WHERE id = :id AND r2_key IS NULL"
                ), {"key": r2_key, "id": job_id})

            log.info("OK %s → %s", job_id, r2_key)
            migrated += 1

        except Exception as e:
            log.error("FAILED %s — %s: %s", job_id, type(e).__name__, e)
            failed += 1

    log.info("Done — migrated: %d | skipped: %d | failed: %d", migrated, skipped, failed)

if __name__ == "__main__":
    main()
