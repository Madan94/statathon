"""Checkpoint Store — Redis-backed with file fallback.

Per-pass caching for the extraction pipeline. Saves intermediate results
so re-runs skip expensive passes (VLM calls, Gemini reasoning).

Features:
- Auto-invalidation on model/config change (config_hash included in key)
- Redis primary (fast, shared across processes, TTL-based expiry)
- File fallback (when Redis is down or not configured)
- Graceful: never crashes the pipeline if cache fails

Usage:
    from report_builder.checkpoint_store import CheckpointStore
    ckpt = CheckpointStore(source_hash="abc123def456")
    
    cached = ckpt.load("pass2_entities")
    if cached:
        entity_pages = cached
    else:
        entity_pages = expensive_extraction(...)
        ckpt.save("pass2_entities", entity_pages)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CheckpointStore:
    """Per-pipeline checkpoint manager with Redis + file fallback.
    
    Modes:
        fresh  — New upload. Never loads from cache. Saves progress for resume.
        resume — Pipeline broke midway. Loads cached passes, skips re-running them.
    """

    def __init__(self, source_hash: str, mode: str = "fresh"):
        self.file_hash = source_hash[:12] if source_hash else "unknown"
        self.config_hash = self._compute_config_hash()[:8]
        self.prefix = os.getenv("REDIS_CHECKPOINT_PREFIX", "ckpt")
        self.enabled = os.getenv("CHECKPOINT_ENABLED", "true").lower() in ("1", "true", "yes")
        self.backend = os.getenv("CHECKPOINT_BACKEND", "auto")  # auto | redis | file
        self.mode = mode  # "fresh" = new upload, "resume" = continue from break

        self._redis = None
        self._file_dir = Path(os.getenv("CHECKPOINT_DIR", "./checkpoints")) / f"{self.file_hash}_{self.config_hash}"

        if self.enabled:
            self._file_dir.mkdir(parents=True, exist_ok=True)
            if self.backend in ("auto", "redis"):
                self._redis = self._connect_redis()

        # Fresh mode: clear ALL old cache for this file to ensure clean run
        if self.mode == "fresh" and self.enabled:
            self.invalidate()
            logger.info("[checkpoint] store=fresh (new upload) — cleared old cache for %s", self.file_hash)
        
        logger.info("[checkpoint] store=%s mode=%s file_hash=%s config_hash=%s redis=%s",
                    "enabled" if self.enabled else "disabled",
                    self.mode,
                    self.file_hash, self.config_hash,
                    "connected" if self._redis else "file-only")

    def _compute_config_hash(self) -> str:
        """Hash of model/provider config. Changes → cache miss (auto-invalidation)."""
        parts = [
            "v6",  # bump this to invalidate ALL caches after pipeline logic changes
            os.getenv("SGLANG_MODEL", ""),
            os.getenv("LAYOUTLM_MODEL_ID", ""),
            os.getenv("VLM_PROVIDER", ""),
            os.getenv("REASONING_PROVIDER", ""),
            os.getenv("GEMINI_MODEL", ""),
            os.getenv("PROVIDER_ENTITY_EXTRACTION", ""),
        ]
        return hashlib.md5("|".join(parts).encode()).hexdigest()

    def _connect_redis(self):
        """Try connecting to Redis. Returns client or None."""
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis
            client = redis.from_url(redis_url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
            client.ping()
            return client
        except ImportError:
            logger.debug("[checkpoint] redis package not installed — using file backend")
        except Exception as e:
            logger.debug("[checkpoint] Redis unavailable (%s) — using file backend", e)
        return None

    def _key(self, pass_name: str) -> str:
        """Build Redis key: ckpt:{file_hash}:{config_hash}:{pass_name}"""
        return f"{self.prefix}:{self.file_hash}:{self.config_hash}:{pass_name}"

    def _ttl_seconds(self, pass_name: str) -> int:
        """TTL for a pass. LLM passes = 24h, others = 7 days."""
        if any(x in pass_name for x in ("pass2", "pass3", "entities", "questions")):
            return int(os.getenv("REDIS_CHECKPOINT_TTL_LLM_HOURS", "24")) * 3600
        return int(os.getenv("REDIS_CHECKPOINT_TTL_HOURS", "168")) * 3600

    def save(self, pass_name: str, data: Any) -> None:
        """Save pass result to cache (Redis first, file fallback)."""
        if not self.enabled:
            return
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            logger.debug("[checkpoint] JSON serialize failed for %s: %s", pass_name, e)
            return

        # Redis
        if self._redis:
            try:
                self._redis.setex(self._key(pass_name), self._ttl_seconds(pass_name), payload)
                logger.debug("[checkpoint] Saved to Redis: %s (%d bytes)", pass_name, len(payload))
                return
            except Exception as e:
                logger.debug("[checkpoint] Redis save failed for %s: %s", pass_name, e)

        # File fallback
        try:
            fpath = self._file_dir / f"{pass_name}.json"
            fpath.write_text(payload, encoding="utf-8")
            logger.debug("[checkpoint] Saved to file: %s", fpath.name)
        except Exception as e:
            logger.debug("[checkpoint] File save failed for %s: %s", pass_name, e)

    def load(self, pass_name: str) -> Any | None:
        """Load pass result from cache. Returns None on miss or in fresh mode."""
        if not self.enabled:
            return None
        # Fresh mode: never load from cache — always re-run
        if self.mode == "fresh":
            return None

        # Redis
        if self._redis:
            try:
                val = self._redis.get(self._key(pass_name))
                if val is not None:
                    logger.info("[checkpoint] ✓ Redis hit: %s", pass_name)
                    return json.loads(val)
            except Exception:
                pass

        # File fallback
        fpath = self._file_dir / f"{pass_name}.json"
        if fpath.exists():
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                logger.info("[checkpoint] ✓ File hit: %s", pass_name)
                return data
            except Exception:
                pass

        return None

    def invalidate(self, pass_name: str = "") -> None:
        """Clear specific pass or all passes for this PDF+config."""
        if self._redis:
            if pass_name:
                self._redis.delete(self._key(pass_name))
            else:
                # Clear all keys for this file+config
                pattern = f"{self.prefix}:{self.file_hash}:{self.config_hash}:*"
                for key in self._redis.scan_iter(pattern):
                    self._redis.delete(key)

        # File
        if pass_name:
            fpath = self._file_dir / f"{pass_name}.json"
            if fpath.exists():
                fpath.unlink()
        else:
            import shutil
            shutil.rmtree(self._file_dir, ignore_errors=True)

    def exists(self, pass_name: str) -> bool:
        """Quick check if a pass result is cached (without loading)."""
        if not self.enabled:
            return False
        if self._redis:
            try:
                return bool(self._redis.exists(self._key(pass_name)))
            except Exception:
                pass
        return (self._file_dir / f"{pass_name}.json").exists()
