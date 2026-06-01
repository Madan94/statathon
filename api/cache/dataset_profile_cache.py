"""Redis cache for persisted dataset profiles (fallback: in-process)."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_PREFIX = "dataset:"
CACHE_SUFFIX = ":profile"
DEFAULT_TTL = int(os.getenv("DATASET_PROFILE_CACHE_TTL_SECONDS", "86400"))


class _InMemoryProfileCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        rec = self._store.get(key)
        if not rec:
            return None
        expires, val = rec
        if time.time() > expires:
            self._store.pop(key, None)
            return None
        return val

    def setex(self, key: str, ttl: int, val: str) -> None:
        self._store[key] = (time.time() + ttl, val)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


_fallback = _InMemoryProfileCache()


def profile_cache_key(dataset_id: int) -> str:
    return f"{CACHE_PREFIX}{dataset_id}{CACHE_SUFFIX}"


class DatasetProfileCache:
    def __init__(self, redis_url: str | None = None) -> None:
        self._client = None
        url = redis_url or os.getenv("REDIS_URL")
        if url:
            try:
                import redis  # type: ignore

                self._client = redis.from_url(url, decode_responses=True)
                self._client.ping()
            except Exception as exc:
                logger.info("Dataset profile cache using in-process fallback: %s", exc)
                self._client = None

    def get(self, dataset_id: int) -> dict[str, Any] | None:
        key = profile_cache_key(dataset_id)
        raw: str | None = None
        if self._client:
            try:
                raw = self._client.get(key)
            except Exception:
                raw = _fallback.get(key)
        else:
            raw = _fallback.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set(self, dataset_id: int, payload: dict[str, Any], ttl: int = DEFAULT_TTL) -> None:
        key = profile_cache_key(dataset_id)
        body = json.dumps(payload)
        if self._client:
            try:
                self._client.setex(key, ttl, body)
                return
            except Exception:
                pass
        _fallback.setex(key, ttl, body)

    def invalidate(self, dataset_id: int) -> None:
        key = profile_cache_key(dataset_id)
        if self._client:
            try:
                self._client.delete(key)
                return
            except Exception:
                pass
        _fallback.delete(key)
