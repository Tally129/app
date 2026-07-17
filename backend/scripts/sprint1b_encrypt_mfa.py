"""
Sprint 1b migration: encrypt any plaintext TOTP secrets at rest.

Idempotent — safe to re-run. Skips docs whose `mfa_secret` already starts with
the `enc-v1:` prefix.

Run: `python /app/backend/scripts/sprint1b_encrypt_mfa.py`
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from auth_utils import encrypt_mfa_secret  # noqa: E402


async def main() -> int:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    total = 0
    migrated = 0
    async for u in db.users.find({"mfa_secret": {"$exists": True, "$ne": None}}):
        total += 1
        s = u.get("mfa_secret") or ""
        if s.startswith("enc-v1:"):
            continue
        try:
            new_val = encrypt_mfa_secret(s)
        except Exception as e:
            print(f"[migrate1b] SKIP {u.get('email')}: {e}")
            continue
        await db.users.update_one({"id": u["id"]}, {"$set": {"mfa_secret": new_val}})
        migrated += 1
    print(f"[migrate1b] Scanned {total} accounts with a mfa_secret; encrypted {migrated}.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
