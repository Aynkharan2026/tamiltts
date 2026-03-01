#!/usr/bin/env python3
"""
Purge jobs older than N days (default 30). Removes DB records and output files.

Usage:
    python scripts/purge_old_jobs.py --days 30 [--dry-run]
"""
import argparse
import os
import sys
import shutil
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import Job, JobChunk, ShareToken
from app.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    db = SessionLocal()
    try:
        old_jobs = db.query(Job).filter(Job.created_at < cutoff).all()
        print(f"Found {len(old_jobs)} jobs older than {args.days} days")

        for job in old_jobs:
            job_dir = os.path.join(settings.OUTPUT_DIR, job.id)
            if not args.dry_run:
                if os.path.isdir(job_dir):
                    shutil.rmtree(job_dir, ignore_errors=True)
                db.query(ShareToken).filter(ShareToken.job_id == job.id).delete()
                db.query(JobChunk).filter(JobChunk.job_id == job.id).delete()
                db.delete(job)
                print(f"  Deleted job {job.id} ({job.title})")
            else:
                print(f"  [dry-run] Would delete job {job.id} ({job.title})")

        if not args.dry_run:
            db.commit()
            print("Done.")
        else:
            print("Dry run complete — no changes made.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
