"""Long-Term Memory (LTM) backed by Qdrant Cloud.

Collections:
  - plfs_corrections: User edits to ScribeAgent narratives (learning signal)
  - plfs_styles: Domain-specific style patterns (sentence templates)
  - entity_bindings: Historical entity→column bindings (boost future accuracy)

All operations are graceful no-ops if Qdrant is not configured.

Env vars:
  QDRANT_URL          - Qdrant Cloud endpoint (e.g. https://xxx.aws.cloud.qdrant.io:6333)
  QDRANT_API_KEY      - API key for Qdrant Cloud
  LTM_EMBEDDING_MODEL - Embedding model name (default: sentence-transformers/all-MiniLM-L6-v2)
  LTM_ENABLED         - "0" to disable (default: "1" if QDRANT_URL is set)
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Collection names
COLLECTION_CORRECTIONS = "plfs_corrections"
COLLECTION_STYLES = "plfs_styles"
COLLECTION_BINDINGS = "entity_bindings"

_EMBEDDING_DIM = 384  # MiniLM-L6 default


@dataclass
class LTMConfig:
    """Configuration for long-term memory."""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "LTMConfig":
        url = os.getenv("QDRANT_URL", "")
        return cls(
            qdrant_url=url,
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            embedding_model=os.getenv(
                "LTM_EMBEDDING_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            ),
            enabled=url != "" and os.getenv("LTM_ENABLED", "1") != "0",
        )


class LTMStore:
    """Qdrant-backed long-term memory store.

    Gracefully degrades to no-op if Qdrant is unreachable.
    """

    def __init__(self, config: LTMConfig | None = None):
        self._config = config or LTMConfig.from_env()
        self._client: Any = None
        self._embedder: Any = None
        self._initialized = False

        if self._config.enabled:
            self._init_client()

    def _init_client(self) -> None:
        """Initialize Qdrant client and ensure collections exist."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = QdrantClient(
                url=self._config.qdrant_url,
                api_key=self._config.qdrant_api_key,
                timeout=10,
            )

            # Ensure collections exist
            existing = {c.name for c in self._client.get_collections().collections}
            for name in (COLLECTION_CORRECTIONS, COLLECTION_STYLES, COLLECTION_BINDINGS):
                if name not in existing:
                    self._client.create_collection(
                        collection_name=name,
                        vectors_config=VectorParams(
                            size=_EMBEDDING_DIM,
                            distance=Distance.COSINE,
                        ),
                    )
                    logger.info("Created LTM collection: %s", name)

            self._initialized = True
            logger.info("LTM store initialized: %s", self._config.qdrant_url)
        except ImportError:
            logger.debug("qdrant-client not installed, LTM disabled")
        except Exception as exc:
            logger.warning("LTM init failed: %s", exc)

    def _embed(self, text: str) -> list[float]:
        """Generate embedding for text."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self._config.embedding_model)
            except ImportError:
                # Fallback: simple hash-based pseudo-embedding (for testing)
                logger.debug("sentence-transformers not installed, using hash fallback")
                self._embedder = "hash_fallback"

        if self._embedder == "hash_fallback":
            return self._hash_embed(text)

        return self._embedder.encode(text).tolist()

    @staticmethod
    def _hash_embed(text: str) -> list[float]:
        """Deterministic pseudo-embedding for testing (NOT for production)."""
        h = hashlib.sha256(text.encode()).digest()
        # Expand to _EMBEDDING_DIM floats in [-1, 1]
        import struct
        values: list[float] = []
        data = h * ((_EMBEDDING_DIM * 4 // len(h)) + 1)
        for i in range(_EMBEDDING_DIM):
            b = data[i * 2:(i * 2) + 2]
            values.append((int.from_bytes(b, "big") / 32767.5) - 1.0)
        return values

    @property
    def is_available(self) -> bool:
        """Check if LTM is configured and ready."""
        return self._initialized

    # --- Corrections collection ---

    def store_correction(
        self,
        original: str,
        corrected: str,
        context: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Store a user correction to ScribeAgent output.

        Returns the point ID if stored, None if LTM unavailable.
        """
        if not self._initialized:
            return None

        text = f"{context} | {original} → {corrected}"
        embedding = self._embed(text)
        point_id = hashlib.md5(text.encode()).hexdigest()

        try:
            from qdrant_client.models import PointStruct
            self._client.upsert(
                collection_name=COLLECTION_CORRECTIONS,
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "original": original,
                        "corrected": corrected,
                        "context": context,
                        "timestamp": time.time(),
                        **(metadata or {}),
                    },
                )],
            )
            return point_id
        except Exception as exc:
            logger.warning("Failed to store correction: %s", exc)
            return None

    def query_corrections(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Find relevant past corrections for a narrative context."""
        if not self._initialized:
            return []

        try:
            embedding = self._embed(query)
            results = self._client.search(
                collection_name=COLLECTION_CORRECTIONS,
                query_vector=embedding,
                limit=limit,
                score_threshold=min_score,
            )
            return [
                {"score": r.score, **r.payload}
                for r in results
            ]
        except Exception as exc:
            logger.debug("Correction query failed: %s", exc)
            return []

    # --- Styles collection ---

    def store_style(
        self,
        pattern: str,
        domain: str = "plfs",
        category: str = "general",
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Store a style pattern (sentence template, comparison format, etc.)."""
        if not self._initialized:
            return None

        embedding = self._embed(f"{domain} {category}: {pattern}")
        point_id = hashlib.md5(f"{domain}:{pattern}".encode()).hexdigest()

        try:
            from qdrant_client.models import PointStruct
            self._client.upsert(
                collection_name=COLLECTION_STYLES,
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "pattern": pattern,
                        "domain": domain,
                        "category": category,
                        "timestamp": time.time(),
                        **(metadata or {}),
                    },
                )],
            )
            return point_id
        except Exception as exc:
            logger.warning("Failed to store style: %s", exc)
            return None

    def query_styles(
        self,
        context: str,
        domain: str = "plfs",
        limit: int = 3,
        min_score: float = 0.6,
    ) -> list[dict[str, Any]]:
        """Find relevant style patterns for a given context."""
        if not self._initialized:
            return []

        try:
            embedding = self._embed(f"{domain}: {context}")
            results = self._client.search(
                collection_name=COLLECTION_STYLES,
                query_vector=embedding,
                limit=limit,
                score_threshold=min_score,
            )
            return [{"score": r.score, **r.payload} for r in results]
        except Exception as exc:
            logger.debug("Style query failed: %s", exc)
            return []

    # --- Entity bindings collection ---

    def store_binding(
        self,
        entity_name: str,
        column_name: str,
        dataset_id: str = "",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Store a confirmed entity→column binding for future reuse."""
        if not self._initialized:
            return None

        text = f"{entity_name} → {column_name}"
        embedding = self._embed(text)
        point_id = hashlib.md5(f"{dataset_id}:{text}".encode()).hexdigest()

        try:
            from qdrant_client.models import PointStruct
            self._client.upsert(
                collection_name=COLLECTION_BINDINGS,
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "entity_name": entity_name,
                        "column_name": column_name,
                        "dataset_id": dataset_id,
                        "confidence": confidence,
                        "timestamp": time.time(),
                        **(metadata or {}),
                    },
                )],
            )
            return point_id
        except Exception as exc:
            logger.warning("Failed to store binding: %s", exc)
            return None

    def query_bindings(
        self,
        entity_name: str,
        limit: int = 5,
        min_score: float = 0.75,
    ) -> list[dict[str, Any]]:
        """Find historical bindings for an entity name."""
        if not self._initialized:
            return []

        try:
            embedding = self._embed(entity_name)
            results = self._client.search(
                collection_name=COLLECTION_BINDINGS,
                query_vector=embedding,
                limit=limit,
                score_threshold=min_score,
            )
            return [{"score": r.score, **r.payload} for r in results]
        except Exception as exc:
            logger.debug("Binding query failed: %s", exc)
            return []


# Singleton instance
_store: LTMStore | None = None


def get_ltm_store() -> LTMStore:
    """Get the singleton LTM store instance."""
    global _store
    if _store is None:
        _store = LTMStore()
    return _store


def reset_ltm_store() -> None:
    """Reset the singleton (for testing)."""
    global _store
    _store = None
