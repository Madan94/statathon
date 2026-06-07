"""In-process TTL cache for assembled analysis payloads (dedupe parallel wizard requests)."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_lock = threading.Lock()
_cache: dict[tuple[int, int, bool], tuple[float, dict[str, Any]]] = {}
TTL_SECONDS = int(os.getenv("ANALYSIS_PAYLOAD_CACHE_TTL", "120"))


def _now() -> float:
    return time.monotonic()


def get_cached_payload(
    analysis_id: int,
    normalization_version: int | None,
    *,
    include_phase3: bool,
) -> dict[str, Any] | None:
    key = (analysis_id, int(normalization_version or 0), include_phase3)
    with _lock:
        entry = _cache.get(key)
        if not entry:
            return None
        expires_at, payload = entry
        if _now() >= expires_at:
            del _cache[key]
            return None
        return dict(payload)


def set_cached_payload(
    analysis_id: int,
    normalization_version: int | None,
    *,
    include_phase3: bool,
    payload: dict[str, Any],
) -> None:
    key = (analysis_id, int(normalization_version or 0), include_phase3)
    with _lock:
        _cache[key] = (_now() + TTL_SECONDS, dict(payload))


def invalidate_analysis_cache(analysis_id: int) -> None:
    with _lock:
        for key in [k for k in _cache if k[0] == analysis_id]:
            del _cache[key]
