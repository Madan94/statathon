"""Phase 2 — Stateful Memory Engine (STM + LTM).

Short-Term Memory (STM) — Redis:
  * Active job session: pagination cursors, in-flight block IDs, BI chat
    history, generation queue. TTL bounded (default 1 hour).

Long-Term Memory (LTM) — Qdrant Reflection Ledger:
  * Vector store of MoSPI methodological rulebooks (seeded at deploy time).
  * Every human correction is upserted as a new point with semantic embedding,
    so the system learns from feedback and improves narrative alignment with
    official standards over time.
  * A Postgres mirror (`report_corrections`) keeps the relational audit trail.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------- STM ----------------

class _InMemoryStore:
    def __init__(self):
        self._d: dict[str, tuple[float, str]] = {}

    def setex(self, key: str, ttl: int, val: str):
        self._d[key] = (time.time() + ttl, val)

    def get(self, key: str):
        rec = self._d.get(key)
        if not rec:
            return None
        expires, val = rec
        if time.time() > expires:
            self._d.pop(key, None)
            return None
        return val

    def delete(self, key: str):
        self._d.pop(key, None)


class STM:
    """Redis-backed if available, else in-process. Same API either way."""

    _fallback = _InMemoryStore()

    def __init__(self, redis_url: str | None = None):
        self._client = None
        url = redis_url or os.getenv("REDIS_URL")
        if url:
            try:
                import redis  # type: ignore

                self._client = redis.from_url(url, decode_responses=True)
                self._client.ping()
            except Exception as exc:
                logger.info("STM falling back to in-process: %s", exc)
                self._client = None

    def put(self, job_id: int, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        full = f"rb:{job_id}:{key}"
        payload = json.dumps(value)
        if self._client:
            try:
                self._client.setex(full, ttl_seconds, payload)
                return
            except Exception:
                pass
        self._fallback.setex(full, ttl_seconds, payload)

    def get(self, job_id: int, key: str) -> Any | None:
        full = f"rb:{job_id}:{key}"
        if self._client:
            try:
                raw = self._client.get(full)
                if raw is not None:
                    return json.loads(raw)
            except Exception:
                pass
        raw = self._fallback.get(full)
        return json.loads(raw) if raw else None


# ---------------- LTM (Qdrant Reflection Ledger) ----------------

_QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "statathon_reflections")
_EMBED_DIM = int(os.getenv("QDRANT_EMBED_DIM", "384"))


def _qdrant_client():
    """Best-effort Qdrant client; returns None if unreachable on this host."""
    try:
        from qdrant_client import QdrantClient  # type: ignore

        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        api_key = os.getenv("QDRANT_API_KEY") or None
        client = QdrantClient(url=url, api_key=api_key, timeout=2.0)
        # Verify reachable
        client.get_collections()
        return client
    except Exception as exc:
        logger.info("Qdrant unreachable: %s", exc)
        return None


def _embed_text(text: str) -> list[float] | None:
    """Sentence-Transformers embedding for Qdrant points. None if model unavailable."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        model_name = os.getenv("LTM_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        model = SentenceTransformer(model_name)
        return model.encode(text).tolist()
    except Exception:
        return None


class ReflectionLedger:
    """Qdrant-backed LTM with Postgres mirror for audit.

    Each correction is stored as:
      * Qdrant point (vector + payload) for semantic retrieval
      * `report_corrections` row for relational integrity
    """

    def __init__(self, db: Session):
        self.db = db
        self._qdrant = _qdrant_client()
        if self._qdrant:
            self._ensure_collection()

    def _ensure_collection(self):
        try:
            from qdrant_client.http.models import Distance, VectorParams  # type: ignore

            existing = {c.name for c in self._qdrant.get_collections().collections}
            if _QDRANT_COLLECTION not in existing:
                self._qdrant.create_collection(
                    collection_name=_QDRANT_COLLECTION,
                    vectors_config=VectorParams(size=_EMBED_DIM, distance=Distance.COSINE),
                )
        except Exception as exc:
            logger.info("Qdrant collection init failed: %s", exc)

    def record_correction(
        self,
        *,
        job_id: int,
        block_id: str,
        kind: str,
        before: str | None,
        after: str | None,
        diagnostics: dict[str, Any] | None = None,
    ) -> int:
        from database.models import ReportCorrection

        row = ReportCorrection(
            job_id=job_id,
            block_id=block_id,
            correction_kind=kind,
            before_text=before,
            after_text=after,
            diagnostics=diagnostics or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        # Upsert into Qdrant (best-effort).
        if self._qdrant:
            try:
                from qdrant_client.http.models import PointStruct  # type: ignore

                vec = _embed_text(after or before or "") if after or before else None
                if vec:
                    self._qdrant.upsert(
                        collection_name=_QDRANT_COLLECTION,
                        points=[PointStruct(
                            id=int(row.id),
                            vector=vec,
                            payload={
                                "job_id": job_id,
                                "block_id": block_id,
                                "kind": kind,
                                "before": before,
                                "after": after,
                            },
                        )],
                    )
            except Exception as exc:
                logger.info("Qdrant upsert failed: %s", exc)
        return int(row.id)

    def retrieve_similar(self, block_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Semantic retrieval via Qdrant; falls back to keyword scan of Postgres mirror."""
        if self._qdrant:
            try:
                vec = _embed_text(query)
                if vec:
                    hits = self._qdrant.search(
                        collection_name=_QDRANT_COLLECTION,
                        query_vector=vec,
                        limit=limit,
                    )
                    return [
                        {
                            "id": h.id,
                            "block_id": h.payload.get("block_id"),
                            "kind": h.payload.get("kind"),
                            "before": h.payload.get("before"),
                            "after": h.payload.get("after"),
                            "score": h.score,
                        }
                        for h in hits
                    ]
            except Exception as exc:
                logger.info("Qdrant search failed: %s", exc)

        from database.models import ReportCorrection

        q = (
            self.db.query(ReportCorrection)
            .filter(ReportCorrection.block_id == block_id)
            .order_by(ReportCorrection.created_at.desc())
            .limit(limit * 4)
            .all()
        )
        tokens = {t.lower() for t in (query or "").split() if len(t) > 3}
        scored: list[tuple[int, dict[str, Any]]] = []
        for r in q:
            text = " ".join(filter(None, [r.before_text or "", r.after_text or ""])).lower()
            score = sum(1 for t in tokens if t in text)
            scored.append((score, {
                "id": r.id,
                "block_id": r.block_id,
                "kind": r.correction_kind,
                "before": r.before_text,
                "after": r.after_text,
                "diagnostics": r.diagnostics,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]
