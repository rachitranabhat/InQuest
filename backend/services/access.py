"""Public-demo access controls (server-side). Off unless the environment sets them, so local use is unchanged.

PRISM_DEMO_ACCESS_CODE  if set, starting a reviewer session requires this shared code; live-AI requests require a session.
PRISM_LLM_DAILY_LIMIT   if > 0, at most this many live-AI requests (reports, copilot, investigations) per UTC day
                        per server process; further requests get 429 and Demo mode keeps working.
This is demo access control for synthetic data, not production authentication.
"""
from __future__ import annotations

import hmac
import os
import threading
from datetime import datetime, timezone

from fastapi import HTTPException

_LOCK = threading.Lock()
_USED = {"day": "", "n": 0}


def access_code() -> str:
    return os.getenv("PRISM_DEMO_ACCESS_CODE", "").strip()


def daily_limit() -> int:
    try:
        return max(0, int(os.getenv("PRISM_LLM_DAILY_LIMIT", "0")))
    except ValueError:
        return 0


def check_code(given: str | None) -> None:
    code = access_code()
    if code and not hmac.compare_digest((given or "").encode(), code.encode()):
        raise HTTPException(401, "A valid demo access code is required to start a reviewer session.")


def writes(reviewer: dict | None) -> None:
    """With an access code set, anonymous visitors can read but not create reports or copilot messages."""
    if access_code() and reviewer is None:
        raise HTTPException(401, "Start a reviewer session (demo access code required) to do this.")


def live_ai(mode: str, reviewer: dict | None) -> None:
    """Call before any request that may use the OpenAI API."""
    if mode != "llm":
        return
    if access_code() and reviewer is None:
        raise HTTPException(401, "Live AI requires a reviewer session. Demo mode is available without one.")
    limit = daily_limit()
    if not limit:
        return
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _LOCK:
        if _USED["day"] != day:
            _USED.update(day=day, n=0)
        if _USED["n"] >= limit:
            raise HTTPException(429, "Today's live-AI demo limit has been reached. Demo mode still works.")
        _USED["n"] += 1
