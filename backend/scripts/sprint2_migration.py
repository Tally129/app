"""
Sprint 2 migration:
  * Creates refresh_tokens + login_continuations collections + indexes.
  * Adds idle_timeout_minutes + absolute_expires_at to user_sessions rows.
  * Revokes any pre-Sprint-2 sessions so the user re-logs in once (Sprint 2
    accepts only opaque refresh tokens; the old refresh JWTs would be honoured
    by the old code and are rejected by the new /auth/refresh endpoint).

Run: `python /app/backend/scripts/sprint2_migration.py`
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))


async def main() -> int:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # refresh_tokens indexes
    await db.refresh_tokens.create_index("token_hash", unique=True)
    await db.refresh_tokens.create_index([("family_id", 1), ("generation", 1)])
    await db.refresh_tokens.create_index([("session_id", 1), ("revoked_at", 1)])
    await db.refresh_tokens.create_index("expires_at", expireAfterSeconds=0)

    # login_continuations indexes (short-lived tickets)
    await db.login_continuations.create_index("ticket_id", unique=True)
    await db.login_continuations.create_index("expires_at", expireAfterSeconds=0)

    # user_sessions backfill
    now = datetime.now(timezone.utc)
    workforce_idle = int(os.environ.get("WORKFORCE_IDLE_TIMEOUT_MIN", "15"))
    workforce_abs = int(os.environ.get("WORKFORCE_ABSOLUTE_SESSION_HOURS", "12"))
    client_idle = int(os.environ.get("CLIENT_IDLE_TIMEOUT_MIN", "60"))
    client_abs = int(os.environ.get("CLIENT_ABSOLUTE_SESSION_DAYS", "7"))
    r1 = await db.user_sessions.update_many(
        {"idle_timeout_minutes": {"$exists": False}},
        {"$set": {"idle_timeout_minutes": workforce_idle}},
    )
    r2 = await db.user_sessions.update_many(
        {"absolute_expires_at": {"$exists": False}},
        [{"$set": {"absolute_expires_at": {
            "$ifNull": ["$expires_at", now + timedelta(hours=workforce_abs)]}}}],
    )
    print(f"[migrate2] idle_timeout_minutes set on {r1.modified_count} sessions")
    print(f"[migrate2] absolute_expires_at set on {r2.modified_count} sessions")

    # Revoke every pre-Sprint-2 session — no matching refresh_tokens row exists.
    r3 = await db.user_sessions.update_many(
        {"revoked_at": None},
        {"$set": {"revoked_at": now, "revoke_reason": "sprint2_upgrade"}},
    )
    print(f"[migrate2] Sprint-1 sessions retired: {r3.modified_count}")

    print("[migrate2] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
