"""Simple in-memory rate limiting for auth endpoints."""

from __future__ import annotations

import os
import time
from collections import defaultdict

_window = int(os.getenv("AUTH_RATE_WINDOW_SECONDS", "3600"))
_max = int(os.getenv("AUTH_RATE_MAX_PER_WINDOW", "20"))

_buckets: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str) -> bool:
    """Return True if allowed, False if rate limited."""
    now = time.time()
    hits = _buckets[key]
    hits[:] = [t for t in hits if now - t < _window]
    if len(hits) >= _max:
        return False
    hits.append(now)
    return True
