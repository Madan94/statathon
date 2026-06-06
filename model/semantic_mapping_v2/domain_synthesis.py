"""
STEP 4 — Domain Synthesis Layer (Unified Domain Registry).

Merges static domains (STEP 2) and dynamic domains (STEP 3) WITHOUT prioritising
either, producing a single unified registry that is the source of truth for
matching. The registry is materialised in Qdrant:

  * static domains  -> shared collection, namespaced by usecase + embedding
                       signature (so different providers/usecases never clash);
  * dynamic domains -> per-dataset collection (recreated each run).

Each unified entry carries: domain_id, domain_name, domain_type, description.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from semantic_mapping_v2.config import (
    STATIC_DOMAINS_COLLECTION,
    dynamic_domains_collection,
)
from semantic_mapping_v2.domain_loader import Domain, DomainRegistryLoader
from semantic_mapping_v2.dynamic_domains import DynamicDomainGenerator
from semantic_mapping_v2.embedder import SemanticEmbedder
from semantic_mapping_v2.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)


def _point_id(namespace: str, text: str) -> int:
    digest = hashlib.sha256(f"{namespace}:{text}".encode("utf-8")).hexdigest()
    # Qdrant accepts unsigned 64-bit int ids; take 63 bits to stay positive.
    return int(digest[:16], 16) >> 1


class UnifiedDomainRegistry:
    """Builds and serves the merged static+dynamic domain registry via Qdrant."""

    def __init__(
        self,
        embedder: SemanticEmbedder | None = None,
        loader: DomainRegistryLoader | None = None,
        generator: DynamicDomainGenerator | None = None,
    ):
        self.embedder = embedder or SemanticEmbedder()
        self.loader = loader or DomainRegistryLoader()
        self.generator = generator or DynamicDomainGenerator()
        self.store = QdrantVectorStore(dim=self.embedder.dim)
        self.domains: dict[str, Domain] = {}

    # -- collection names (namespaced by embedding signature) ----------------
    def _static_collection(self, usecase: str) -> str:
        return f"{STATIC_DOMAINS_COLLECTION}_{usecase}_{self.embedder.signature}"

    def _dynamic_collection(self, dataset_id: str) -> str:
        return f"{dynamic_domains_collection(dataset_id)}_{self.embedder.signature}"

    # -- build ---------------------------------------------------------------
    def build(
        self,
        *,
        usecase: str,
        dataset_id: str,
        dataset_name: str,
        column_names: list[str],
        sample_values: dict[str, list[Any]] | None = None,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        """Load static, generate dynamic, merge, and seed Qdrant. Returns summary."""
        static_domains = self.loader.load_domains(usecase)

        dynamic_domains: list[Domain] = []
        llm_used = False
        if use_llm:
            dynamic_domains = self.generator.generate(
                usecase=usecase,
                dataset_name=dataset_name,
                static_domains=static_domains,
                column_names=column_names,
                sample_values=sample_values or {},
            )
            llm_used = bool(dynamic_domains)

        # Merge without priority: dedupe by normalized name, static wins identity
        # only to avoid duplicates (not ranking).
        merged: dict[str, Domain] = {}
        for d in static_domains:
            merged[d.domain_name.lower()] = d
        for d in dynamic_domains:
            if d.domain_name.lower() not in merged:
                merged[d.domain_name.lower()] = d
        self.domains = {d.domain_id: d for d in merged.values()}

        static_ready = self._seed_static(usecase, static_domains)
        dynamic_ready = self._seed_dynamic(dataset_id, dynamic_domains) if dynamic_domains else False

        return {
            "usecase": usecase,
            "static_count": len(static_domains),
            "dynamic_count": len(dynamic_domains),
            "unified_count": len(self.domains),
            "llm_used": llm_used,
            "static_ready": static_ready,
            "dynamic_ready": dynamic_ready,
            "static_collection": self._static_collection(usecase),
            "dynamic_collection": self._dynamic_collection(dataset_id) if dynamic_domains else None,
            "domains": [d.to_dict() for d in self.domains.values()],
        }

    def _seed_static(self, usecase: str, domains: list[Domain]) -> bool:
        if not domains:
            return False
        collection = self._static_collection(usecase)
        if not self.store.ensure_collection(collection):
            return False
        # Idempotent: re-seed only when the count doesn't match (versioned packs).
        if self.store.count(collection) == len(domains):
            return True
        texts = [d.embed_text() for d in domains]
        vectors = self.embedder.embed_documents_batch(texts)
        ids = [_point_id(collection, d.domain_id) for d in domains]
        payloads = [self._payload(d) for d in domains]
        return self.store.upsert(collection, ids, [v.tolist() for v in vectors], payloads)

    def _seed_dynamic(self, dataset_id: str, domains: list[Domain]) -> bool:
        collection = self._dynamic_collection(dataset_id)
        # Recreate so stale dynamic domains from prior runs never linger.
        if not self.store.ensure_collection(collection, recreate=True):
            return False
        texts = [d.embed_text() for d in domains]
        vectors = self.embedder.embed_documents_batch(texts)
        ids = [_point_id(collection, d.domain_id) for d in domains]
        payloads = [self._payload(d) for d in domains]
        return self.store.upsert(collection, ids, [v.tolist() for v in vectors], payloads)

    @staticmethod
    def _payload(d: Domain) -> dict[str, Any]:
        return {
            "domain_id": d.domain_id,
            "domain_name": d.domain_name,
            "domain_type": d.domain_type,
            "description": d.description,
            "usecase": d.usecase,
            "synonyms": d.synonyms,
        }

    # -- search --------------------------------------------------------------
    def search(
        self,
        usecase: str,
        dataset_id: str,
        query_vector: list[float],
        *,
        include_dynamic: bool = True,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search unified registry (static usecase collection + dynamic dataset)."""
        collections = [self._static_collection(usecase)]
        if include_dynamic:
            collections.append(self._dynamic_collection(dataset_id))

        hits: list[dict[str, Any]] = []
        for collection in collections:
            for h in self.store.search(collection, query_vector, limit=limit):
                hits.append(
                    {
                        "score": h["score"],
                        "collection": collection,
                        "payload": h["payload"],
                    }
                )
        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits[:limit]

    def get_domain(self, domain_name: str) -> Domain | None:
        for d in self.domains.values():
            if d.domain_name.lower() == str(domain_name).lower():
                return d
        return None
