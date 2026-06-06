"""
Semantic Mapping Pipeline V2 — Qdrant + BGE-M3 + Gemini domain titles.

Parallel to model/semantic_mapping/; does not import that package.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from semantic_mapping_v2.config import (
    STATIC_DOMAINS_COLLECTION,
    STRICT_THRESHOLD,
    columns_collection,
    dynamic_domains_collection,
)
from semantic_mapping_v2.embedder import BgeM3Embedder
from semantic_mapping_v2.normalization import ColumnPreprocessorV2
from semantic_mapping_v2.registry_manager import RegistryManager, get_qdrant_client

logger = logging.getLogger(__name__)


def _point_id(namespace: str, text: str) -> str:
    digest = hashlib.sha256(f"{namespace}:{text}".encode("utf-8")).hexdigest()
    return digest[:32]


class SemanticPipelineV2:
    """
    V2 entry point: normalize → ingest metadata → LLM domains → Qdrant search → gatekeeper.
    """

    def __init__(self):
        self.preprocessor = ColumnPreprocessorV2()
        self.embedder = BgeM3Embedder()
        self.registry = RegistryManager(embedder=self.embedder)

    def run(
        self,
        dataset_id: str,
        columns: list[str],
        dataset_metadata: dict[str, Any] | None = None,
        *,
        dynamic_titles: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Args:
            dataset_id: Unique dataset identifier (scopes Qdrant collections).
            columns: Raw column names.
            dataset_metadata: JSON metadata with keys such as dataset_archetype,
                datatypes, column_metadata, and optional extra ingestion fields.
        """
        meta = dataset_metadata or {}
        archetype = str(meta.get("dataset_archetype") or meta.get("dataset_type") or "unknown")
        datatypes = meta.get("datatypes") or {}
        column_metadata = meta.get("column_metadata") or {}

        normalized = self.preprocessor.normalize_columns(columns)

        static_ready = self.registry.ensure_static_domains()

        llm_used = False
        if dynamic_titles is None:
            try:
                from services.gemini_domain_generator_v2 import generate_domain_titles

                dynamic_titles = generate_domain_titles(
                    dataset_archetype=archetype,
                    column_names=columns,
                    datatypes=datatypes if isinstance(datatypes, dict) else {},
                    column_metadata=column_metadata if isinstance(column_metadata, dict) else {},
                )
            except Exception as exc:
                logger.warning("LLM domain generation error: %s", exc)
                dynamic_titles = None

        if dynamic_titles:
            self.registry.upsert_dynamic_domains(dataset_id, dynamic_titles)
            print(
                f"✨ LLM Generated Domains: "
                f"{[d.get('domain_name') if isinstance(d, dict) else d for d in dynamic_titles]}"
            )
            llm_used = True
        elif dynamic_titles is None:
            logger.info("LLM domain generation failed; using static_domains only.")

        self._upsert_column_vectors(dataset_id, normalized)

        semantic_mapping: dict[str, dict[str, Any]] = {}
        for col in columns:
            norm_text = normalized[col]
            query_vec = self.embedder.embed_query(norm_text).tolist()
            hits = self.registry.search_domains(
                query_vec,
                dataset_id,
                include_dynamic=llm_used,
                limit=5,
            )
            print(f"\nDEBUG: Analyzing column '{col}' (Normalized: '{norm_text}')")
            if hits:
                for i, hit in enumerate(hits):
                    print(f"  Hit {i+1}: {hit['payload'].get('title', hit['payload'].get('subdomain'))} | Score: {hit['score']:.4f}")
            else:
                print("  No hits returned from Qdrant.")
            best_score = float(hits[0]["score"]) if hits else 0.0
            best_payload = hits[0]["payload"] if hits else {}

            if best_score >= STRICT_THRESHOLD and hits:
                if best_payload.get("source") == "dynamic":
                    domain = str(best_payload.get("title") or "unknown")
                else:
                    domain = str(best_payload.get("subdomain") or best_payload.get("keyword") or "unknown")
                routing_path = "qdrant_semantic_match"
            else:
                domain = "uncorrelated"
                routing_path = "uncorrelated_sink"

            semantic_mapping[col] = {
                "normalized_name": norm_text,
                "domain": domain,
                "confidence": round(best_score, 4),
                "routing_path": routing_path,
                "top_match": hits[0] if hits else None,
                "explainability": {
                    "dataset_archetype": archetype,
                    "engine": "semantic_mapping_v2",
                    "strict_threshold": STRICT_THRESHOLD,
                    "llm_domains_used": llm_used,
                    "static_registry_ready": static_ready,
                },
            }

        return {
            "engine_version": "v2",
            "dataset_id": dataset_id,
            "dataset_context": {
                "dataset_type": archetype,
                "metadata": meta,
            },
            "semantic_mapping": semantic_mapping,
            "domain_registry": {
                "static_collection": STATIC_DOMAINS_COLLECTION if static_ready else None,
                "dynamic_collection": dynamic_domains_collection(dataset_id),
                "dynamic_titles": dynamic_titles or [],
                "llm_used": llm_used,
            },
            "column_normalization": [
                {"column": c, "normalized": normalized[c]} for c in columns
            ],
        }

    def _upsert_column_vectors(self, dataset_id: str, normalized: dict[str, str]) -> None:
        """Store normalized column query vectors in Qdrant for traceability."""
        client = get_qdrant_client()
        if not client:
            return

        collection = columns_collection(dataset_id)
        if not self.registry._ensure_collection(collection):
            return

        try:
            from qdrant_client.http.models import PointStruct

            points = []
            for col, text in normalized.items():
                vec = self.embedder.embed_query(text)
                points.append(
                    PointStruct(
                        id=_point_id(collection, col),
                        vector=vec.tolist(),
                        payload={
                            "column_name": col,
                            "normalized_text": text,
                            "dataset_id": str(dataset_id),
                        },
                    )
                )
            if points:
                client.upsert(collection_name=collection, points=points)
        except Exception as exc:
            logger.debug("Column vector upsert skipped: %s", exc)
