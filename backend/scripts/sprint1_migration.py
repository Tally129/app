"""
Sprint 1 migration script.

Idempotent — safe to run multiple times.
  • Creates user_sessions, password_reset_tokens, password_reset_attempts collections + indexes.
  • Backfills `session_version=1` and `password_changed_at` on existing users.
  • In HIPAA_MODE=on, refuses to proceed if seeded predictable passwords remain.

Run: `python /app/backend/scripts/sprint1_migration.py`
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))
from auth_utils import verify_password  # noqa: E402


SEEDED_PREDICTABLE = {
    ("admin@natmedsol.local",       "Admin!2345"),
    ("tallyravello@gmail.com",      "TEST123"),
    ("ravello@natmedsol.local",     "Ravello!2345"),
    ("frontdesk@natmedsol.local",   "FrontDesk!2345"),
    ("auditor@natmedsol.local",     "Auditor!2345"),
}


def _hipaa_mode() -> bool:
    return os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}


async def main() -> int:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # --- 1. Indexes ------------------------------------------------------ #
    print("[migrate] Creating indexes …")
    await db.user_sessions.create_index("id", unique=True)
    await db.user_sessions.create_index([("user_id", 1), ("revoked_at", 1)])
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)

    await db.password_reset_tokens.create_index("token_hash", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.password_reset_tokens.create_index([("user_id", 1), ("consumed_at", 1)])

    await db.password_reset_attempts.create_index([("email_hash", 1), ("ts", -1)])
    await db.password_reset_attempts.create_index([("ip", 1), ("ts", -1)])
    await db.password_reset_attempts.create_index("ts")

    # --- 2. Backfill user session_version + password_changed_at ---------- #
    print("[migrate] Backfilling users …")
    now = datetime.now(timezone.utc)
    r1 = await db.users.update_many(
        {"session_version": {"$exists": False}},
        {"$set": {"session_version": 1}},
    )
    r2 = await db.users.update_many(
        {"password_changed_at": {"$exists": False}},
        [{"$set": {"password_changed_at": {"$ifNull": ["$created_at", now]}}}],
    )
    print(f"[migrate]   session_version set on {r1.modified_count} users")
    print(f"[migrate]   password_changed_at set on {r2.modified_count} users")
    r3 = await db.users.update_many(
        {"$or": [{"created_at": None}, {"created_at": {"$exists": False}}]},
        {"$set": {"created_at": now}},
    )
    print(f"[migrate]   created_at backfilled on {r3.modified_count} users")

    # --- 3. HIPAA-mode seeded-credential guard --------------------------- #
    if _hipaa_mode():
        print("[migrate] HIPAA_MODE=on — checking for seeded predictable credentials …")
        offenders: list[str] = []
        async for u in db.users.find({}, {"email": 1, "password_hash": 1}):
            for seed_email, seed_pw in SEEDED_PREDICTABLE:
                if u.get("email") == seed_email and u.get("password_hash"):
                    if verify_password(seed_pw, u["password_hash"]):
                        offenders.append(seed_email)
                        break
        if offenders:
            print("[migrate] BLOCKED — the following accounts still use predictable seeded passwords:")
            for e in offenders:
                print(f"           - {e}")
            print("[migrate] Rotate these passwords (or delete the accounts) and rerun.")
            return 2

    print("[migrate] Done.")
    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
