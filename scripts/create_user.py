#!/usr/bin/env python3
"""
Create a user account.

Usage:
    python scripts/create_user.py --email admin@example.com --password secretpass [--admin]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import User
from app.auth import hash_password


def main():
    parser = argparse.ArgumentParser(description="Create a TamilTTS user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--admin", action="store_true", default=False)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == args.email.lower().strip()).first()
        if existing:
            print(f"ERROR: User {args.email} already exists.")
            sys.exit(1)

        user = User(
            email=args.email.lower().strip(),
            hashed_password=hash_password(args.password),
            is_admin=args.admin,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created user: {user.email} (id={user.id}, admin={user.is_admin})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
