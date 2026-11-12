"""Admin CLI: python -m app.cli <command>"""
from __future__ import annotations

import argparse
import getpass
import json
import secrets
import sys
from pathlib import Path

from sqlalchemy import select

from .core import emit
from .db import SessionLocal
from .discovery import load_profile
from .models import Company, User
from .security import hash_password

SEED = Path(__file__).parent / "data" / "companies_seed.json"


def create_user(username: str, password: str | None, generate: bool) -> None:
    if generate:
        password = secrets.token_urlsafe(18)
    elif not password:
        password = getpass.getpass("Password (min 12 chars): ")
        if password != getpass.getpass("Repeat: "):
            sys.exit("Passwords do not match")
    if len(password) < 12:
        sys.exit("Password must be at least 12 characters")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(User(username=username, password_hash=hash_password(password)))
            action = "created"
        else:
            user.password_hash = hash_password(password)
            action = "password reset for"
        db.commit()
    print(f"User {action} “{username}”.")
    if generate:
        print(f"Generated password: {password}")


def seed_companies() -> None:
    data = json.loads(SEED.read_text())
    added = 0
    with SessionLocal() as db:
        for c in data:
            exists = db.scalar(select(Company.id).where(Company.provider == c["provider"], Company.board_token == c["board_token"]))
            if not exists:
                db.add(Company(name=c["name"], provider=c["provider"], board_token=c["board_token"]))
                added += 1
        load_profile(db)
        if added:
            emit(db, "sources.seeded", f"{added} verified job sources added.")
        db.commit()
    print(f"{added} sources added ({len(data)} in seed list).")


def main() -> None:
    ap = argparse.ArgumentParser(prog="sonic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("create-user")
    u.add_argument("username")
    u.add_argument("--password")
    u.add_argument("--generate", action="store_true")
    sub.add_parser("seed")
    sub.add_parser("discover")
    a = ap.parse_args()
    if a.cmd == "create-user":
        create_user(a.username, a.password, a.generate)
    elif a.cmd == "seed":
        seed_companies()
    elif a.cmd == "discover":
        from .discovery import run_discovery
        with SessionLocal() as db:
            out = run_discovery(db, trigger="cli")
            out.pop("new_ids", None)
            print(out)


if __name__ == "__main__":
    main()
