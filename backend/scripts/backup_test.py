"""
CLI: create one encrypted backup and immediately run a dry-run restore.

Usage:
    BACKUP_ENC_KEY_B64=$(python -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())') \
    python scripts/backup_test.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backup import backup_now, restore_verify


def main():
    if not os.environ.get("BACKUP_ENC_KEY_B64"):
        print("ERROR: BACKUP_ENC_KEY_B64 must be set", file=sys.stderr)
        sys.exit(2)
    meta = backup_now(operator_id="backup_test.py")
    print("BACKUP OK:")
    print(json.dumps(meta, indent=2, default=str))
    result = restore_verify(meta["path"])
    print("RESTORE VERIFY OK:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
