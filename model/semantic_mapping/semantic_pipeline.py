import json
from pathlib import Path

from semantic_mapping.column_preprocessor import ColumnPreprocessor
from semantic_mapping.bert_embedder import BertEmbedder
from semantic_mapping.domain_repository import DomainRepository
from semantic_mapping.similarity_engine import SimilarityEngine
from semantic_mapping.confidence_engine import ConfidenceEngine
from semantic_mapping.priority_mapper import PriorityMapper
from semantic_mapping.cluster_engine import ClusterEngine
from semantic_mapping.schema_graph import SchemaGraph
from semantic_mapping.context_inference import ContextInference
from semantic_mapping.dataset_context_inferencer import DatasetContextInferencer
from semantic_mapping.dynamic_domain_generator import DynamicDomainGenerator
from semantic_mapping.semantic_cluster_engine import SemanticClusterEngine
from storage.vector_store import VectorStore
from audit.audit_logger import AuditLogger


_ARCHETYPE_TO_LEGACY_CONTEXT = {
    "health_survey": "health",
    "education_statistics": "education",
    "labor": "labor",
    "economic_survey": "socioeconomic",
    "agriculture": "socioeconomic",
    "infrastructure": "infrastructure",
    "socioeconomic": "socioeconomic",
    "census": "census",
    "survey_metadata": "socioeconomic",
}


class SemanticPipeline:

    def __init__(self, vector_cache_dir: str | None = None):
        root = Path(__file__).resolve().parent.parent
        cache = vector_cache_dir or str(root / "storage" / "vector_cache")
        self.vector_store = VectorStore(cache_dir=cache)
        self.preprocessor = ColumnPreprocessor()
        self.embedder = BertEmbedder(vector_store=self.vector_store)
        self.domain_repo = DomainRepository()
        self.sim_engine = SimilarityEngine()
        self.conf_engine = ConfidenceEngine()
        self.priority_mapper = PriorityMapper()
        self.cluster_engine = ClusterEngine()
        self.semantic_clusters = SemanticClusterEngine(self.cluster_engine)
        self.schema_graph = SchemaGraph()
        self.context_engine = ContextInference(self.embedder)
        self.dataset_inferencer = DatasetContextInferencer(self.embedder)
        self.dynamic_gen = DynamicDomainGenerator()
        self.audit = AuditLogger()

    def run(self, columns: list[str], column_enrichment: dict[str, str] | None = None) -> dict:
        self.audit.clear()
        self.domain_repo.clear_runtime()

        normalized = self.preprocessor.normalize_columns(columns)
        if column_enrichment:
            for col in columns:
                extra = (column_enrichment.get(col) or "").strip()
                if extra:
                    base = normalized.get(col) or ""
                    normalized[col] = f"{base}. Profile signals: {extra}"
        column_tokens = {col: self.preprocessor.extract_tokens(col) for col in columns}
        self.audit.log("column_normalization", {"columns": normalized}, step=1)

        column_embeddings = self.embedder.embed_dict(normalized)
        embedding_dim = len(next(iter(column_embeddings.values()))) if column_embeddings else 0
        self.audit.log(
            "embedding_generation",
            {"columns_embedded": list(column_embeddings.keys()), "embedding_dim": embedding_dim},
            step=2,
        )

        column_texts = list(normalized.values())
        structured_ctx = self.dataset_inferencer.infer(column_texts)
        dataset_context_scores = structured_ctx.domain_scores
        archetype = structured_ctx.dataset_type

        if not columns:
            return {
                "dataset_context": {
                    "dataset_type": archetype,
                    "domain_scores": {k: round(v, 4) for k, v in dataset_context_scores.items()},
                    "legacy_alignment_context": _ARCHETYPE_TO_LEGACY_CONTEXT.get(archetype, "socioeconomic"),
                },
                "semantic_mapping": {},
                "clusters": [],
                "priority_dependencies": {},
                "schema_graph": {"nodes": [], "edges": []},
                "column_cluster_map": {},
                "audit_records": list(self.audit.records),
            }

        self.audit.log(
            "dataset_context_inferencer",
            {"dataset_type": archetype, "domain_scores": {k: round(v, 4) for k, v in dataset_context_scores.items()}},
            step=3,
        )

        base_desc = self.domain_repo.get_base_domain_descriptions()
        base_emb_batch = self.embedder.embed_batch(list(base_desc.values()))
        base_embeddings = {name: base_emb_batch[base_desc[name]] for name in base_desc}

        provisional_domains: dict[str, str] = {}
        for col in columns:
            emb = column_embeddings[col]
            scores = self.sim_engine.compute_domain_similarity(emb, base_embeddings)
            provisional_domains[col] = max(scores, key=scores.get)

        dynamic_specs = self.dynamic_gen.generate(
            archetype,
            normalized,
            column_embeddings,
            provisional_domains,
        )
        self.domain_repo.merge_runtime(dynamic_specs)
        self.audit.log(
            "dynamic_domains_registered",
            {"domains": list(dynamic_specs.keys()), "count": len(dynamic_specs)},
            step=4,
        )

        domain_descriptions = self.domain_repo.get_domain_descriptions()
        domain_embeddings = self.embedder.embed_batch(list(domain_descriptions.values()))
        domain_embeddings = {name: domain_embeddings[domain_descriptions[name]] for name in domain_descriptions}

        legacy_ctx = _ARCHETYPE_TO_LEGACY_CONTEXT.get(archetype, "socioeconomic")

        column_domains: dict[str, str] = {}
        domain_scores_all: dict[str, dict[str, float]] = {}

        for col in columns:
            emb = column_embeddings[col]
            embedding_scores = self.sim_engine.compute_domain_similarity(emb, domain_embeddings)
            tokens = column_tokens[col]

            keyword_boost = {}
            for domain_name in self.domain_repo.get_domain_names():
                keywords = self.domain_repo.get_domain_keywords(domain_name)
                keyword_boost[domain_name] = self.sim_engine.compute_keyword_boost(tokens, keywords)

            cb_legacy = self.context_engine.get_context_boost(tokens, legacy_ctx)
            cb_arch = self.context_engine.archetype_keyword_overlap(tokens, archetype)
            context_boost = max(cb_legacy, cb_arch)

            combined_scores = self.context_engine.compute_domain_scores_with_context(
                embedding_scores, keyword_boost, context_boost
            )

            adjusted = self._optional_gemini_adjust(col, combined_scores, archetype)
            if adjusted is not None:
                combined_scores = adjusted

            domain_scores_all[col] = combined_scores
            column_domains[col] = max(combined_scores, key=combined_scores.get)

        self.audit.log(
            "domain_prediction",
            {col: {"domain": column_domains[col], "scores": domain_scores_all[col]} for col in columns},
            step=5,
        )

        clusters, cluster_info = self.semantic_clusters.cluster(
            column_embeddings, column_domains, domain_scores_all
        )

        for cluster_id, info in cluster_info.items():
            if info["support"] >= 0.6:
                for member in info["members"]:
                    current_domain = column_domains[member]
                    cluster_domain = info["domain"]
                    if current_domain != cluster_domain:
                        member_scores = domain_scores_all[member]
                        best_score = member_scores.get(current_domain, 0)
                        cluster_score = member_scores.get(cluster_domain, 0)
                        if best_score - cluster_score < 0.05:
                            column_domains[member] = cluster_domain

        self.audit.log(
            "clustering",
            {"clusters": {cid: info for cid, info in cluster_info.items()}, "column_domains_after_reinforcement": column_domains},
            step=6,
        )

        self.schema_graph.build_graph(column_embeddings, clusters, column_domains)
        edge_pairs = sum(len(v) for v in self.schema_graph.edges.values()) // 2
        self.audit.log(
            "schema_graph",
            {"node_count": len(self.schema_graph.nodes), "edge_pairs": edge_pairs},
            step=7,
        )

        results: dict[str, dict] = {}
        for col in columns:
            cluster_support = self.conf_engine.compute_cluster_support(col, column_domains[col], column_domains, clusters)
            graph_consistency = self.conf_engine.compute_graph_consistency(
                col, column_domains[col], self.schema_graph.edges, column_domains
            )
            confidence = self.conf_engine.calculate_confidence(
                domain_scores_all[col],
                cluster_support=cluster_support,
                graph_consistency=graph_consistency,
            )
            scores = domain_scores_all[col]
            best_d = column_domains[col]
            top_entries = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
            emb_top = float(top_entries[0][1]) if top_entries else 0.0
            kw = self.sim_engine.compute_keyword_boost(column_tokens[col], self.domain_repo.get_domain_keywords(best_d))
            cb_legacy = self.context_engine.get_context_boost(column_tokens[col], legacy_ctx)
            cb_arch = self.context_engine.archetype_keyword_overlap(column_tokens[col], archetype)
            ctx_b = max(cb_legacy, cb_arch)

            results[col] = {
                "normalized_name": normalized[col],
                "domain": best_d,
                "confidence": confidence,
                "top_domain_scores": dict(top_entries),
                "cluster_support": round(cluster_support, 4),
                "graph_consistency": round(graph_consistency, 4),
                "explainability": {
                    "matching_reason": (
                        f"Assigned '{best_d}' by fusion of embedding similarity to domain prototypes "
                        f"(top score {emb_top:.4f}), keyword overlap ({kw:.4f}), "
                        f"dataset archetype '{archetype}' contextual alignment ({ctx_b:.4f}), "
                        f"cluster cohesion ({cluster_support:.4f}), graph consistency ({graph_consistency:.4f})."
                    ),
                    "domain_support": round(float(scores.get(best_d, 0.0)), 4),
                    "contextual_support": round(ctx_b, 4),
                    "embedding_similarity": round(emb_top, 4),
                    "keyword_overlap_primary_domain": round(kw, 4),
                    "dataset_archetype": archetype,
                },
            }

        self.audit.log(
            "confidence_scoring",
            {
                col: {
                    "confidence": results[col]["confidence"],
                    "cluster_support": results[col]["cluster_support"],
                    "graph_consistency": results[col]["graph_consistency"],
                }
                for col in columns
            },
            step=8,
        )

        dependencies = self.priority_mapper.compute_priority(column_embeddings, self.schema_graph, clusters)
        self.audit.log("dependency_inference", {col: deps for col, deps in dependencies.items()}, step=9)

        cluster_output = []
        column_cluster_map: dict[str, str] = {}
        for cluster_id, info in cluster_info.items():
            for m in info["members"]:
                column_cluster_map[m] = cluster_id
            cluster_output.append(
                {
                    "cluster_id": cluster_id,
                    "domain": info["domain"],
                    "support_score": round(float(info.get("support_score", info["support"])), 4),
                    "support": round(float(info["support"]), 4),
                    "columns": info["members"],
                    "domain_distribution": info.get("domain_distribution", {}),
                }
            )

        return {
            "dataset_context": {
                "dataset_type": archetype,
                "domain_scores": {k: round(v, 4) for k, v in dataset_context_scores.items()},
                "legacy_alignment_context": legacy_ctx,
            },
            "semantic_mapping": results,
            "clusters": cluster_output,
            "priority_dependencies": dependencies,
            "schema_graph": self.schema_graph.to_dict(),
            "column_cluster_map": column_cluster_map,
            "audit_records": list(self.audit.records),
        }

    def _optional_gemini_adjust(self, column: str, combined_scores: dict[str, float], archetype: str):
        try:
            from services.gemini_semantic_fallback import apply_gemini_domain_adjustment
        except ImportError:
            return None
        try:
            return apply_gemini_domain_adjustment(column_name=column, scores=combined_scores, archetype=archetype)
        except Exception:
            return None

    def print_audit_log(self, event_type=None, limit=None):
        records = self.audit.get_records(event_type)
        if limit is not None:
            records = records[:limit]

        print("=== Audit log records ===")
        for record in records:
            step = record.get("step", "n/a")
            data = json.dumps(record["data"], default=str, indent=2)
            print(f"[step {step}] event={record['event']}\n{data}\n")

    def print_domain_predictions(self, result: dict):
        mapping = result.get("semantic_mapping", {})
        print("=== Domain predictions ===")
        for column, details in mapping.items():
            scores = details.get("top_domain_scores", {})
            score_text = ", ".join(f"{domain}:{score:.3f}" for domain, score in scores.items())
            print(
                f"{column}: domain={details.get('domain')} confidence={details.get('confidence', 0.0):.4f} "
                f"normalized='{details.get('normalized_name')}' top_scores=[{score_text}]"
            )
