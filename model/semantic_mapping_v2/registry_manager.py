"""
Qdrant lifecycle for static and dynamic domain registries (V2).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from semantic_mapping_v2.config import (
    DOMAIN_DEFINITIONS_PATH,
    EMBED_DIM,
    QDRANT_API_KEY,
    QDRANT_TIMEOUT_SEC,
    QDRANT_UPSERT_BATCH_SIZE,
    QDRANT_URL,
    STATIC_DOMAINS_COLLECTION,
    dynamic_domains_collection,
)
from semantic_mapping_v2.embedder import BgeM3Embedder

logger = logging.getLogger(__name__)


def _point_id(namespace: str, text: str) -> str:
    digest = hashlib.sha256(f"{namespace}:{text}".encode("utf-8")).hexdigest()
    return digest[:32]


def get_qdrant_client():
    try:
        from qdrant_client import QdrantClient

        return QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            timeout=QDRANT_TIMEOUT_SEC,
        )
    except Exception as exc:
        logger.warning("Qdrant client unavailable: %s", exc)
        return None


class RegistryManager:
    """Manages static_domains seeding and per-dataset dynamic domain collections."""

    def __init__(self, embedder: BgeM3Embedder | None = None):
        self.embedder = embedder or BgeM3Embedder()
        self.client = get_qdrant_client()
        self._nonempty_collections: set[str] = set()

    def _ensure_collection(self, name: str) -> bool:
        if not self.client:
            return False
        try:
            from qdrant_client.http.models import Distance, VectorParams

            existing = {c.name for c in self.client.get_collections().collections}
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
                )
            return True
        except Exception as exc:
            logger.warning("Failed to ensure collection %s: %s", name, exc)
            return False

    def _collection_count(self, name: str) -> int:
        if not self.client:
            return 0
        try:
            info = self.client.count(collection_name=name, exact=True)
            count = int(info.count)
            if count > 0:
                self._nonempty_collections.add(name)
            return count
        except Exception:
            return 0

    def _upsert_points_batched(self, collection: str, points: list[Any]) -> bool:
        if not self.client or not points:
            return False
        try:
            batch_size = max(1, QDRANT_UPSERT_BATCH_SIZE)
            for i in range(0, len(points), batch_size):
                self.client.upsert(
                    collection_name=collection,
                    points=points[i : i + batch_size],
                )
            self._nonempty_collections.add(collection)
            return True
        except Exception as exc:
            logger.warning("Upsert failed on %s: %s", collection, exc)
            return False

    def ensure_static_domains(self) -> bool:
        """Seed static_domains from domain_definitions.json when empty."""
        if not self._ensure_collection(STATIC_DOMAINS_COLLECTION):
            return False
        if STATIC_DOMAINS_COLLECTION in self._nonempty_collections:
            logger.info("static_domains already populated; skipping seed.")
            return True
        if self._collection_count(STATIC_DOMAINS_COLLECTION) > 0:
            logger.info("static_domains already populated; skipping seed.")
            return True
        if not DOMAIN_DEFINITIONS_PATH.exists():
            logger.error("domain_definitions.json not found at %s", DOMAIN_DEFINITIONS_PATH)
            return False

        ontology = json.loads(DOMAIN_DEFINITIONS_PATH.read_text(encoding="utf-8"))
        points: list[Any] = []
        texts: list[str] = []
        payloads: list[dict[str, Any]] = []

        for tier_name, tier_data in (ontology.get("dataset_types") or {}).items():
            for sub_name, keywords in (tier_data.get("subdomains") or {}).items():
                entries = [sub_name.replace("_", " ")] + list(keywords)
                for kw in entries:
                    text = str(kw).strip()
                    if not text:
                        continue
                    texts.append(text)
                    payloads.append(
                        {
                            "tier": tier_name,
                            "subdomain": sub_name,
                            "keyword": text,
                            "text": text,
                            "source": "static",
                        }
                    )

        if not texts:
            return False

        print(
            f"      [registry] Embedding {len(texts)} static domain texts (first seed only)...",
            flush=True,
        )
        vectors = self.embedder.embed_documents_batch(texts)
        try:
            from qdrant_client.http.models import PointStruct

            for text, vec, payload in zip(texts, vectors, payloads):
                points.append(
                    PointStruct(
                        id=_point_id(STATIC_DOMAINS_COLLECTION, text),
                        vector=vec.tolist(),
                        payload=payload,
                    )
                )
            if not self._upsert_points_batched(STATIC_DOMAINS_COLLECTION, points):
                return False
            logger.info("Seeded %d static domain vectors into %s", len(points), STATIC_DOMAINS_COLLECTION)
            print(f"      [registry] Seeded {len(points)} static domain vectors.", flush=True)
            return True
        except Exception as exc:
            logger.warning("Static domain seed failed: %s", exc)
            return False

    @staticmethod
    def _dynamic_domain_embed_text(domain: dict[str, str] | str) -> str:
        """Build BGE-M3 document text from an LLM domain object."""
        if isinstance(domain, str):
            return domain.strip()
        name = str(domain.get("domain_name") or "").strip()
        summary = str(domain.get("data_value_summary") or "").strip()
        if name and summary:
            return f"{name}. {summary}"
        return name or summary

    @staticmethod
    def _dynamic_domain_name(domain: dict[str, str] | str) -> str:
        if isinstance(domain, str):
            return domain.strip()
        return str(domain.get("domain_name") or "").strip()

    def upsert_dynamic_domains(self, dataset_id: str, domain_titles: list[dict[str, str] | str]) -> bool:
        """Embed and upsert LLM-generated domain objects for a dataset."""
        collection = dynamic_domains_collection(dataset_id)
        if not self._ensure_collection(collection):
            return False
        if not domain_titles:
            return False

        embed_texts = [self._dynamic_domain_embed_text(d) for d in domain_titles]
        vectors = self.embedder.embed_documents_batch(embed_texts)
        try:
            from qdrant_client.http.models import PointStruct

            points = [
                PointStruct(
                    id=_point_id(collection, self._dynamic_domain_name(domain)),
                    vector=vec.tolist(),
                    payload={
                        "title": self._dynamic_domain_name(domain),
                        "domain_name": self._dynamic_domain_name(domain),
                        "data_value_summary": (
                            str(domain.get("data_value_summary") or "").strip()
                            if isinstance(domain, dict)
                            else ""
                        ),
                        "embed_text": embed_text,
                        "dataset_id": str(dataset_id),
                        "source": "dynamic",
                    },
                )
                for domain, embed_text, vec in zip(domain_titles, embed_texts, vectors)
            ]
            if not self._upsert_points_batched(collection, points):
                return False
            logger.info("Upserted %d dynamic domains to %s", len(points), collection)
            return True
        except Exception as exc:
            logger.warning("Dynamic domain upsert failed: %s", exc)
            return False

    def _vector_search(self, collection: str, query_vector: list[float], limit: int) -> list[Any]:
        """Search a collection; supports qdrant-client >=1.7 (query_points) and legacy search()."""
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=collection,
                query=query_vector,
                limit=limit,
            )
            return list(response.points or [])
        return self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=limit,
        )

    def search_domains(
        self,
        query_vector: list[float],
        dataset_id: str,
        *,
        include_dynamic: bool = True,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search static + optional dynamic collections; return merged hits."""
        if not self.client:
            return []

        collections = [STATIC_DOMAINS_COLLECTION]
        if include_dynamic:
            collections.append(dynamic_domains_collection(dataset_id))

        hits: list[dict[str, Any]] = []
        for collection in collections:
            try:
                if collection not in self._nonempty_collections:
                    if self._collection_count(collection) == 0:
                        continue
                results = self._vector_search(collection, query_vector, limit)
                for hit in results:
                    hits.append(
                        {
                            "score": float(hit.score),
                            "collection": collection,
                            "payload": dict(hit.payload or {}),
                        }
                    )
            except Exception as exc:
                logger.warning("Search failed on %s: %s", collection, exc)

        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]
