"""Short-lived in-process cache for phase-status payloads."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_lock = threading.Lock()
_cache: dict[int, tuple[float, dict[str, Any]]] = {}
TTL_SECONDS = int(os.getenv("PHASE_STATUS_CACHE_TTL", "45"))


def get_cached_phase_status(analysis_id: int) -> dict[str, Any] | None:
    with _lock:
        entry = _cache.get(analysis_id)
        if not entry:
            return None
        expires_at, payload = entry
        if time.monotonic() >= expires_at:
            del _cache[analysis_id]
            return None
        return dict(payload)


def set_cached_phase_status(analysis_id: int, payload: dict[str, Any]) -> None:
    with _lock:
        _cache[analysis_id] = (time.monotonic() + TTL_SECONDS, dict(payload))


def invalidate_phase_status(analysis_id: int) -> None:
    with _lock:
        _cache.pop(analysis_id, None)
