"""
Semantic Mapping & Domain Clustering V2 — Production Pipeline.

Orchestrates the full 11-step flow with Qdrant as the vector backbone:

  STEP 1  Usecase detection                  (usecase_detector)
  STEP 2  Static domain loading              (domain_loader)
  STEP 3  Dynamic domain generation (LLM)    (dynamic_domains)
  STEP 4  Domain synthesis -> Qdrant         (domain_synthesis)
  STEP 5  Column feature generation          (feature_extraction)
  STEP 6  Domain matching engine             (matching_engine)
  STEP 7  LLM fallback (< 0.80)              (matching_engine)
  STEP 8  Domain confidence + source         (matching_engine)
  STEP 9  HDBSCAN domain clustering          (clustering)
  STEP 10 Cluster labeling (majority vote)   (clustering)
  STEP 11 Cluster validation (purity)        (clustering)
  +       Schema graph + Knowledge graph     (kg_builder)

FINAL OUTPUT:
    {
      "semantic_mapping":   {column: {domain, confidence, source, ...}},
      "domains":            {domain_name: {...}},        # unified registry
      "dynamic_domains":    {domain_name: {...}},        # LLM-proposed subset
      "clusters":           {cluster_id: {...}},
      "cluster_confidence": {cluster_id: float},
      "usecase": {...}, "schema_graph": {...},
      "knowledge_graph": {...}, "meta": {...}
    }
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import numpy as np
import pandas as pd

from semantic_mapping_v2.clustering import DomainClusteringEngine
from semantic_mapping_v2.column_enricher import enrich_column_features
from semantic_mapping_v2.config import validate_weights
from semantic_mapping_v2.domain_loader import DomainRegistryLoader
from semantic_mapping_v2.domain_synthesis import UnifiedDomainRegistry
from semantic_mapping_v2.dynamic_domains import DynamicDomainGenerator
from semantic_mapping_v2.embedder import SemanticEmbedder
from semantic_mapping_v2.feature_extraction import FeatureExtractor
from semantic_mapping_v2.kg_builder import KnowledgeGraphBuilder, SchemaGraphV2
from semantic_mapping_v2.matching_engine import MatchingEngine
from semantic_mapping_v2.name_canonicalizer import NameRecord, canonicalize_features
from semantic_mapping_v2.usecase_detector import UsecaseDetector

logger = logging.getLogger(__name__)


class SemanticPipelineV2:
    """Production semantic mapping + domain clustering pipeline (Qdrant-backed)."""

    def __init__(self, embedder: SemanticEmbedder | None = None, *, use_llm: bool = True):
        self.embedder = embedder or SemanticEmbedder()
        self.use_llm = use_llm
        self.loader = DomainRegistryLoader()
        self.generator = DynamicDomainGenerator()
        self.detector = UsecaseDetector(self.embedder, self.loader)
        self.features = FeatureExtractor()
        self.registry = UnifiedDomainRegistry(self.embedder, self.loader, self.generator)
        self.matcher = MatchingEngine(self.registry, self.embedder)
        self.clusterer = DomainClusteringEngine()
        self.kg = KnowledgeGraphBuilder()

        issues = validate_weights()
        if issues:
            logger.warning("Score weights do not sum to 1.0: %s", issues)

    # -----------------------------------------------------------------------
    def analyze(
        self,
        df: pd.DataFrame | None = None,
        *,
        dataset_id: str,
        dataset_name: str | None = None,
        columns: list[str] | None = None,
        datatypes: dict[str, str] | None = None,
        samples: dict[str, list[Any]] | None = None,
        file_name: str = "",
        sheet_names: list[str] | None = None,
        user_usecase: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.time()
        dataset_name = dataset_name or dataset_id

        # STEP 5 (features first; they feed every later step) ----------------
        if df is not None:
            features = self.features.from_dataframe(df)
        elif columns:
            features = self.features.from_metadata(columns, datatypes, samples)
        else:
            raise ValueError("analyze() needs either a DataFrame or a columns list.")
        if not features:
            raise ValueError("No columns to analyze.")

        column_names = list(features.keys())
        sample_values = {c: list(f.samples) for c, f in features.items()}

        # STEP 1 — usecase detection (before enrichment so filename hints apply) -
        uc = self.detector.detect(
            column_names=column_names,
            dataset_name=dataset_name,
            file_name=file_name,
            sheet_names=sheet_names or [],
            sample_values=sample_values,
            user_usecase=user_usecase,
        )

        # STEP 5b — LLM column name enrichment (cryptic codes → readable text) -
        # Runs AFTER usecase detection (needs usecase context) and BEFORE
        # embedding (so enriched representations are used for vector search).
        features, enrich_stats = enrich_column_features(
            features,
            usecase=uc.usecase,
            dataset_name=dataset_name,
            use_llm=self.use_llm,
        )

        # STEP 5c — canonical identity. Turn each corrected header phrase into a
        # unique snake_case key and re-key `features` by it, so EVERY later step
        # (embedding, matching, clustering, schema, KG) and all downstream
        # analysis run on the normalized name instead of the raw/cryptic one.
        name_records = canonicalize_features(features)
        renamed: dict[str, Any] = {}
        for raw, feat in features.items():
            rec = name_records[str(raw)]
            feat.original_name = rec.original_name
            feat.name = rec.canonical_name
            feat.display_name = rec.display_name
            renamed[rec.canonical_name] = feat
        features = renamed
        column_names = list(features.keys())
        sample_values = {c: list(f.samples) for c, f in features.items()}

        # One query vector per column, built from (now-enriched) representations.
        reps = [features[c].representation for c in column_names]
        rep_vecs = self.embedder.embed_queries_batch(reps)
        column_vectors = {c: rep_vecs[i] for i, c in enumerate(column_names)}

        # STEP 2-4 — static + dynamic -> unified registry seeded into Qdrant -
        synth = self.registry.build(
            usecase=uc.usecase,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            column_names=column_names,
            sample_values=sample_values,
            use_llm=self.use_llm,
        )
        # Refresh matcher's domain index against the freshly built registry.
        self.matcher = MatchingEngine(self.registry, self.embedder)

        # STEP 6-8 — column -> domain mapping with LLM fallback -------------
        mappings = self.matcher.map_columns(
            usecase=uc.usecase,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            features=features,
            column_query_vectors=column_vectors,
            use_llm=self.use_llm,
        )
        # Carry dtype onto each mapping for downstream KG/use.
        for col, m in mappings.items():
            m.signals.setdefault("_dtype", 0.0)
        column_domains = {c: m.domain for c, m in mappings.items()}

        # STEP 9-11 — clustering, labeling, validation ----------------------
        clusters, column_clusters = self.clusterer.cluster(
            features=features,
            mappings=mappings,
            column_vectors=column_vectors,
            df=df,
        )

        # Schema graph + Knowledge graph ------------------------------------
        schema = SchemaGraphV2().build(column_vectors, column_domains, column_clusters)
        domains_map = self._unified_domains_map(synth)
        knowledge_graph = self.kg.build(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            usecase=uc.usecase,
            usecase_confidence=uc.confidence,
            domains=domains_map,
            mappings=mappings,
            clusters=clusters,
            column_clusters=column_clusters,
            schema_graph=schema,
        )

        return self._assemble_output(
            uc=uc,
            synth=synth,
            domains_map=domains_map,
            mappings=mappings,
            features=features,
            name_records=name_records,
            clusters=clusters,
            schema=schema,
            knowledge_graph=knowledge_graph,
            elapsed=time.time() - t0,
            enrich_stats=enrich_stats,
        )

    # -- output assembly -----------------------------------------------------
    @staticmethod
    def _unified_domains_map(synth: dict[str, Any]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for d in synth.get("domains", []):
            out[d["domain_name"]] = d
        return out

    def _assemble_output(
        self,
        *,
        uc,
        synth: dict[str, Any],
        domains_map: dict[str, dict[str, Any]],
        mappings: dict[str, Any],
        features: dict[str, Any],
        name_records: dict[str, NameRecord],
        clusters: list[Any],
        schema: SchemaGraphV2,
        knowledge_graph: dict[str, Any],
        elapsed: float,
        enrich_stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        semantic_mapping: dict[str, Any] = {}
        for col, m in mappings.items():
            d = m.to_dict()
            d["dtype"] = features[col].dtype
            # Carry identity provenance + UI label on every mapping entry.
            d["original_name"] = features[col].original_name
            d["display_name"] = features[col].display_name
            semantic_mapping[col] = d

        # Raw header -> corrected identity map, persisted for the API/UI overlay.
        column_normalization = [
            {
                **rec.to_dict(),
                "domain": (semantic_mapping.get(rec.canonical_name) or {}).get("domain"),
            }
            for rec in name_records.values()
        ]

        dynamic_domains = {
            name: meta for name, meta in domains_map.items()
            if meta.get("domain_type") == "dynamic"
        }

        clusters_out: dict[str, Any] = {}
        cluster_confidence: dict[str, float] = {}
        for cl in clusters:
            cd = cl.to_dict()
            clusters_out[cd["cluster_id"]] = cd
            cluster_confidence[cd["cluster_id"]] = cd["cluster_confidence"]

        stats = enrich_stats or {}
        llm_fallback_count = sum(1 for m in mappings.values() if m.source == "llm")
        uncorrelated_count = sum(1 for m in mappings.values() if m.source == "uncorrelated")
        embedding_count = sum(1 for m in mappings.values() if m.source == "embedding")

        from semantic_mapping_v2.llm_client import resolve_llm_provider

        llm_provider = resolve_llm_provider() if self.use_llm else "none"

        return {
            "semantic_mapping": semantic_mapping,
            "column_normalization": column_normalization,
            "domains": domains_map,
            "dynamic_domains": dynamic_domains,
            "clusters": clusters_out,
            "cluster_confidence": cluster_confidence,
            "usecase": uc.to_dict(),
            "schema_graph": schema.to_dict(),
            "knowledge_graph": knowledge_graph,
            "meta": {
                "embedding_provider": self.embedder.provider,
                "embedding_model": self.embedder.model_name,
                "embedding_dim": self.embedder.dim,
                "static_domains": synth.get("static_count", 0),
                "dynamic_domains": synth.get("dynamic_count", 0),
                "unified_domains": synth.get("unified_count", 0),
                "llm_used": synth.get("llm_used", False),
                "llm_provider_used": llm_provider,
                "llm_columns_enriched": int(stats.get("llm_enriched") or 0),
                "llm_lookup_enriched": int(stats.get("lookup_enriched") or 0),
                "llm_dynamic_domains": int(synth.get("dynamic_count") or 0),
                "llm_domain_fallback_count": llm_fallback_count,
                "domain_source_embedding": embedding_count,
                "domain_source_uncorrelated": uncorrelated_count,
                "qdrant_static_ready": synth.get("static_ready", False),
                "qdrant_dynamic_ready": synth.get("dynamic_ready", False),
                "elapsed_sec": round(elapsed, 3),
            },
        }
