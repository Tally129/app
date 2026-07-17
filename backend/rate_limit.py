"""
In-memory sliding-window rate limiter + account lockout for authentication and
password-reset endpoints.

Single-node preview scope. For multi-node production, swap the in-memory store
for Redis (same interface). The abuse-control functions never accept or store
tokens, cookies, or passwords — only rate-key + timestamps.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request

from audit import get_client_ip


# Test / preview escape hatch. Off by default; when set truthy, all rate
# gates return "allowed" (useful for high-fanout pytest runs behind a single
# IP). Never enable this in production.
_TEST_MODE = os.environ.get("RATE_LIMIT_TEST_MODE", "").lower() in {"1", "true", "yes", "on"}


class _SlidingWindow:
    def __init__(self, max_events: int, window_sec: int):
        self.max_events = max_events
        self.window_sec = window_sec
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                q = deque()
                self._hits[key] = q
            # Trim expired
            while q and (now - q[0]) > self.window_sec:
                q.popleft()
            if len(q) >= self.max_events:
                retry_after = int(self.window_sec - (now - q[0])) + 1
                return False, max(1, retry_after)
            q.append(now)
            return True, 0

    def reset(self, key: str):
        with self._lock:
            self._hits.pop(key, None)


# Windows (tuned for interactive login UX + brute-force resistance)
_LOGIN_IP = _SlidingWindow(max_events=120, window_sec=60)         # 120/min per IP (multi-user offices)
_LOGIN_EMAIL = _SlidingWindow(max_events=8, window_sec=300)       # 8 attempts / 5min per email
_FORGOT_IP = _SlidingWindow(max_events=20, window_sec=300)        # 20 forgot-password / 5min per IP
_FORGOT_EMAIL = _SlidingWindow(max_events=3, window_sec=900)      # 3 forgot-password / 15min per email

# Account lockout — sliding failure counter, threshold + cooldown
_FAILURE_COUNTER = _SlidingWindow(max_events=1_000_000, window_sec=900)  # dummy window
_LOCK_STATE: Dict[str, float] = {}
_LOCK_LOCK = threading.Lock()
_LOCKOUT_THRESHOLD = 6
_LOCKOUT_COOLDOWN_SEC = 15 * 60


def _client_ip(request: Request) -> str:
    return get_client_ip(request) or "unknown"


def enforce_login_rate(request: Request, email: str):
    if _TEST_MODE:
        return
    ip = _client_ip(request)
    ok, wait = _LOGIN_IP.hit(f"login_ip:{ip}")
    if not ok:
        raise HTTPException(status_code=429, detail={
            "code": "rate_limited",
            "scope": "ip",
            "retry_after_seconds": wait,
        })
    # Only rate-limit per-email if a value is present.
    if email:
        okE, waitE = _LOGIN_EMAIL.hit(f"login_email:{email.lower()}")
        if not okE:
            raise HTTPException(status_code=429, detail={
                "code": "rate_limited",
                "scope": "email",
                "retry_after_seconds": waitE,
            })


def enforce_forgot_rate(request: Request, email: str):
    if _TEST_MODE:
        return
    ip = _client_ip(request)
    ok, wait = _FORGOT_IP.hit(f"forgot_ip:{ip}")
    if not ok:
        raise HTTPException(status_code=429, detail={
            "code": "rate_limited", "scope": "ip", "retry_after_seconds": wait,
        })
    if email:
        okE, waitE = _FORGOT_EMAIL.hit(f"forgot_email:{email.lower()}")
        if not okE:
            raise HTTPException(status_code=429, detail={
                "code": "rate_limited", "scope": "email",
                "retry_after_seconds": waitE,
            })


# --------------------------------------------------------------------------- #
# Account lockout                                                              #
# --------------------------------------------------------------------------- #
def _lock_key(email: str) -> str:
    return f"lock:{(email or '').lower()}"


def record_login_failure(email: str) -> int:
    key = _lock_key(email)
    now = time.time()
    with _LOCK_LOCK:
        count = _LOCK_STATE.get(f"{key}:count", 0) + 1
        _LOCK_STATE[f"{key}:count"] = count
        _LOCK_STATE[f"{key}:last"] = now
        if count >= _LOCKOUT_THRESHOLD:
            _LOCK_STATE[f"{key}:locked_until"] = now + _LOCKOUT_COOLDOWN_SEC
    return count


def reset_login_failures(email: str):
    key = _lock_key(email)
    with _LOCK_LOCK:
        _LOCK_STATE.pop(f"{key}:count", None)
        _LOCK_STATE.pop(f"{key}:last", None)
        _LOCK_STATE.pop(f"{key}:locked_until", None)


def is_locked(email: str) -> Tuple[bool, int]:
    key = _lock_key(email)
    now = time.time()
    with _LOCK_LOCK:
        locked_until = _LOCK_STATE.get(f"{key}:locked_until")
        if locked_until and locked_until > now:
            return True, int(locked_until - now) + 1
        return False, 0
