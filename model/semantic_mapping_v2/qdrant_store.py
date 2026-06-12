"""
Qdrant vector store for Semantic Mapping V2.

Single access point for the Qdrant engine. By default runs Qdrant in
embedded-local mode (on-disk, in-process, no server). If ``QDRANT_URL`` is set
in the environment, connects to that external Qdrant server / cloud instead.

The same collection API is used regardless of mode, so the rest of the pipeline
never needs to know which backend is active.
"""
from __future__ import annotations

import atexit
import logging
import threading
from typing import Any, Sequence

from semantic_mapping_v2.config import (
    QDRANT_API_KEY,
    QDRANT_LOCAL_PATH,
    QDRANT_TIMEOUT_SEC,
    QDRANT_UPSERT_BATCH_SIZE,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)

_CLIENT = None
_CLIENT_LOCK = threading.Lock()


def get_qdrant_client():
    """Return a process-wide Qdrant client (embedded-local or server)."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        from qdrant_client import QdrantClient

        if QDRANT_URL:
            logger.info("Qdrant: connecting to server %s", QDRANT_URL)
            _CLIENT = QdrantClient(
                url=QDRANT_URL,
                api_key=QDRANT_API_KEY,
                timeout=QDRANT_TIMEOUT_SEC,
            )
        else:
            import os

            os.makedirs(QDRANT_LOCAL_PATH, exist_ok=True)
            logger.info("Qdrant: embedded-local at %s", QDRANT_LOCAL_PATH)
            _CLIENT = QdrantClient(path=QDRANT_LOCAL_PATH)
        return _CLIENT


def reset_client() -> None:
    """Drop the cached client (mainly for tests / embedded-lock release)."""
    global _CLIENT
    with _CLIENT_LOCK:
        client = _CLIENT
        _CLIENT = None
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


# Close the embedded client at normal interpreter exit, before finalization,
# so QdrantClient.__del__ doesn't fire while sys.meta_path is already None
# (which prints a benign but noisy ImportError and a non-zero exit).
atexit.register(reset_client)


class QdrantVectorStore:
    """Thin, dependency-light wrapper over the Qdrant collection API."""

    def __init__(self, dim: int):
        self.dim = int(dim)
        self.client = get_qdrant_client()
        self._known_collections: set[str] = set()

    # -- collection lifecycle ------------------------------------------------
    def ensure_collection(self, name: str, *, recreate: bool = False) -> bool:
        from qdrant_client.http.models import Distance, VectorParams

        try:
            exists = self.client.collection_exists(name)
            if exists and recreate:
                self.client.delete_collection(name)
                exists = False
            if not exists:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
                )
            self._known_collections.add(name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant ensure_collection(%s) failed: %s", name, exc)
            return False

    def count(self, name: str) -> int:
        try:
            return int(self.client.count(collection_name=name, exact=True).count)
        except Exception:  # noqa: BLE001
            return 0

    def delete_collection(self, name: str) -> None:
        try:
            if self.client.collection_exists(name):
                self.client.delete_collection(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Qdrant delete_collection(%s) skipped: %s", name, exc)

    # -- writes --------------------------------------------------------------
    def upsert(
        self,
        name: str,
        ids: Sequence[str | int],
        vectors: Sequence[Sequence[float]],
        payloads: Sequence[dict[str, Any]],
    ) -> bool:
        from qdrant_client.http.models import PointStruct

        if not ids:
            return False
        points = [
            PointStruct(id=pid, vector=list(vec), payload=dict(payload))
            for pid, vec, payload in zip(ids, vectors, payloads)
        ]
        try:
            batch = max(1, QDRANT_UPSERT_BATCH_SIZE)
            for i in range(0, len(points), batch):
                self.client.upsert(collection_name=name, points=points[i : i + batch])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant upsert(%s) failed: %s", name, exc)
            return False

    # -- reads ---------------------------------------------------------------
    def search(
        self,
        name: str,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        try:
            if not self.client.collection_exists(name) or self.count(name) == 0:
                return []
            response = self.client.query_points(
                collection_name=name,
                query=list(query_vector),
                limit=limit,
                with_payload=True,
            )
            return [
                {"id": p.id, "score": float(p.score), "payload": dict(p.payload or {})}
                for p in (response.points or [])
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant search(%s) failed: %s", name, exc)
            return []
