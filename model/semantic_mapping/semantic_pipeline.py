import json
import logging
import os
from pathlib import Path
from typing import Any

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
from semantic_mapping.hierarchical_router import HierarchicalDomainRouter
from semantic_mapping.column_normalization_engine import ColumnNormalizationEngine
from storage.vector_store import VectorStore
from audit.audit_logger import AuditLogger
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"


def embedding_model_slug(model_path: str) -> str:
    """Filesystem-safe slug for model-scoped embedding caches."""
    slug = model_path.replace("/", "_").replace("\\", "_").strip()
    return slug or "unknown_model"


def vector_cache_dir_for_model(
    repo_root: Path,
    model_path: str,
    vector_cache_dir: str | None = None,
) -> str:
    """Resolve on-disk cache path; busts legacy MiniLM 384D caches by model name."""
    if vector_cache_dir:
        return vector_cache_dir
    slug = embedding_model_slug(model_path)
    if "bge_m3" in slug or "bge-m3" in slug.lower():
        subdir = "vector_cache_bge_m3"
    else:
        subdir = f"vector_cache_{slug}"
    return str(repo_root / "model" / "storage" / subdir)


# ==========================================
# THE LOCAL HIERARCHY MAP (Replaces Neo4j Macro-Routing)
# ==========================================
LOCAL_HIERARCHY_MAP = {
    # Labor & Employment
    "employment": "labor", "salary": "labor", "workforce": "labor", 
    "industry": "labor", "occupation": "labor", "hours_worked": "labor",
    "labor_mobility": "labor", "benefits": "labor", "retirement": "labor", "unemployment": "labor",
    
    # Economics / Industry
    "financials": "economic_industry", "production": "economic_industry",
    "enterprise": "economic_industry", "fixed_assets": "economic_industry",
    "raw_materials": "economic_industry", "energy": "economic_industry", "labor_cost": "economic_industry",
    
    # Census
    "population": "census", "migration": "census", "literacy": "census", 
    "housing": "census", "income": "census",
    
    # Agriculture
    "crop": "agriculture", "yield": "agriculture", "land": "agriculture", 
    "soil": "agriculture", "irrigation": "agriculture", "fertilizer": "agriculture", 
    "livestock": "agriculture", "climate": "agriculture", "market": "agriculture", "agri_income": "agriculture",
    
    # Health
    "patient": "health", "hospital": "health", "insurance": "health", "disease": "health",
    "treatment": "health", "nutrition": "health", "mortality": "health", "medical_cost": "health",
    "vaccination": "health", "healthcare_access": "health",
    
    # Education
    "student": "education", "attendance": "education", "enrollment": "education",
    "institution": "education", "teacher": "education", "performance": "education",
    "dropout": "education", "scholarship": "education", "curriculum": "education",
    
    # Universal Domains (They map to themselves, no rollup needed)
    "identifier": "identifier",
    "survey_metadata": "survey_metadata",
    "geography": "geography",
    "demographic": "demographic",
    "uncorrelated_metadata": "uncorrelated"
}


class SemanticPipeline:

    def __init__(self, vector_cache_dir: str | None = None):
        repo_root = Path(__file__).resolve().parents[2]
        self.preprocessor = ColumnPreprocessor()
        self.domain_repo = DomainRepository()

        custom_weights = os.getenv("MOSPI_EMBEDDING_MODEL_PATH")
        if custom_weights:
            model_path = custom_weights
        else:
            model_path = os.getenv("SEMANTIC_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)

        cache = vector_cache_dir_for_model(repo_root, model_path, vector_cache_dir)
        os.makedirs(cache, exist_ok=True)
        logger.info("Embedding vector cache directory: %s", cache)

        logger.info("Loading Bi-Encoder from: %s", model_path)
        self.encoder_model = SentenceTransformer(model_path)
        embedding_dim = int(self.encoder_model.get_sentence_embedding_dimension())
        self.vector_store = VectorStore(cache_dir=cache, expected_dim=embedding_dim)

        self.embedder = BertEmbedder(
            model=self.encoder_model,
            model_name=model_path,
            vector_store=self.vector_store,
        )
        
        json_path = str(repo_root / "model" / "config" / "domain_definitions.json")
        self.hierarchical_router = HierarchicalDomainRouter(json_path, self.embedder)
        
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

    def resolve_macro_domain(self, domain_name: str, dataset_archetype: str) -> str:
        """Dual-Tier Resolver for Macro Domain mapping."""
        # 1. Static Resolution
        if domain_name in LOCAL_HIERARCHY_MAP:
            return LOCAL_HIERARCHY_MAP[domain_name]
        
        # 2. Dynamic Identity Preservation
        if domain_name.startswith("dyn_"):
            parts = domain_name.split('_')
            # If it has a valid theme like dyn_labor_123, roll it up to labor
            if len(parts) > 1 and parts[1] in LOCAL_HIERARCHY_MAP.values():
                return parts[1]
            # Otherwise, keep its unique dynamic identity so it doesn't merge into a giant bucket
            return domain_name
                
        # 3. Final Fallback 
        # Trust the engine and return the raw name. NO archetype bucket.
        return domain_name

    def run(
        self,
        columns: list[str],
        dataset_domain: str = None,
        column_enrichment: dict[str, str] | None = None,
        column_profiles: dict[str, Any] | None = None,
    ) -> dict:
        self.audit.clear()
        self.domain_repo.clear_runtime()

        normalized = self.preprocessor.normalize_columns(columns)
        
        # Embed the clean text
        text_for_embedding = {}
        for col in columns:
            base_text = normalized.get(col, col)
            text_for_embedding[col] = base_text
            if column_enrichment:
                extra = (column_enrichment.get(col) or "").strip()
                if extra:
                    text_for_embedding[col] += f". {extra}"
                    
        column_tokens = {col: self.preprocessor.extract_tokens(col) for col in columns}
        self.audit.log("column_normalization", {"columns": normalized}, step=1)

        column_embeddings = self.embedder.embed_dict(text_for_embedding)
        embedding_dim = len(next(iter(column_embeddings.values()))) if column_embeddings else 0
        self.audit.log("embedding_generation", {"columns_embedded": list(column_embeddings.keys()), "embedding_dim": embedding_dim}, step=2)

        # Context Inference
        column_texts = list(normalized.values())
        structured_ctx = self.dataset_inferencer.infer(column_texts)
        dataset_context_scores = structured_ctx.domain_scores
        archetype = structured_ctx.dataset_type

        if not columns:
            return {
                "dataset_context": {"dataset_type": archetype, "domain_scores": dataset_context_scores},
                "semantic_mapping": {}, "clusters": [], "priority_dependencies": {},
                "schema_graph": {"nodes": [], "edges": []}, "column_cluster_map": {},
                "column_normalization": [], "audit_records": list(self.audit.records),
            }

        self.audit.log("dataset_context_inferencer", {"dataset_type": archetype}, step=3)

        # Tracking State
        column_domains: dict[str, str] = {}
        domain_scores_all: dict[str, dict[str, float]] = {}
        column_metadata: dict[str, dict[str, object]] = {}
        routing_by_column: dict[str, dict[str, object]] = {}
        
        locked_columns = []
        unknown_columns = []
        phase_1_scores_by_column: dict[str, dict[str, float]] = {}
        
        # ==========================================
        # PHASE 1: THE GATEKEEPER (Static Ontology Dominance)
        # ==========================================
        STRICT_THRESHOLD = 0.85 

        for col in columns:
            emb = column_embeddings[col]
            
            prediction = self.hierarchical_router.predict_domain(col, emb, archetype)
            routing_by_column[col] = dict(prediction)
            sub_scores = prediction.get("sub_domain_scores")
            if isinstance(sub_scores, dict):
                phase_1_scores_by_column[col] = {
                    k: float(v) for k, v in sub_scores.items()
                }
            static_domain = prediction["predicted_domain"]
            static_score = prediction.get("confidence", 0.0)
            is_locked = bool(prediction.get("is_locked", False))

            if static_score >= STRICT_THRESHOLD or is_locked:
                # FAST-TRACK: Map locally and Lock it.
                final_domain = self.resolve_macro_domain(static_domain, archetype)
                column_domains[col] = final_domain
                column_metadata[col] = {"is_locked": True, "predicted_domain": final_domain}
                domain_scores_all[col] = {final_domain: 1.0, static_domain: static_score}
                locked_columns.append(col)
                self.audit.log("gatekeeper", {"column": col, "status": "locked", "domain": final_domain}, step=4)
            else:
                # FALLBACK QUEUE
                column_metadata[col] = {"is_locked": False, "predicted_domain": "unknown"}
                domain_scores_all[col] = {static_domain: static_score}
                unknown_columns.append(col)
                self.audit.log("gatekeeper", {"column": col, "status": "unknown", "score": static_score}, step=4)

        # ==========================================
        # PHASE 2: INTELLIGENT DYNAMIC FALLBACK
        # ==========================================
        if unknown_columns:
            unknown_normalized = {c: normalized[c] for c in unknown_columns}
            unknown_embeddings = {c: column_embeddings[c] for c in unknown_columns}

            dynamic_specs = self.dynamic_gen.generate(
                dataset_type=archetype,
                normalized_columns=unknown_normalized,
                column_embeddings=unknown_embeddings,
                provisional_domains={},
                dataset_domain=dataset_domain,
                column_phase_1_scores={
                    c: phase_1_scores_by_column[c]
                    for c in unknown_columns
                    if c in phase_1_scores_by_column
                },
                embed_text_fn=self.embedder.embed_text,
            )
            self.domain_repo.merge_runtime(dynamic_specs)

            # Build column → domain AND column → real cohesion confidence
            dyn_mapping: dict[str, str] = {}
            dyn_confidence: dict[str, float] = {}
            for dom_key, spec in dynamic_specs.items():
                meta = spec.get("metadata", {})
                cohesion = float(meta.get("cohesion", 0.75))
                anchor_scores = meta.get("anchor_scores") or {}
                semantic_title = meta.get("semantic_title")
                for member in meta.get("members", []):
                    dyn_mapping[member] = dom_key
                    dyn_confidence[member] = float(
                        anchor_scores.get(member, cohesion)
                    )
                if semantic_title:
                    meta["display_label"] = semantic_title

            # ==========================================
            # PHASE 3: THE UNCORRELATED SINK
            # ==========================================
            for col in unknown_columns:
                new_domain = dyn_mapping.get(col)
                if new_domain:
                    real_conf = dyn_confidence.get(col, 0.75)
                    spec = dynamic_specs.get(new_domain, {})
                    meta = spec.get("metadata", {})
                    display_label = meta.get("display_label") or meta.get(
                        "semantic_title"
                    ) or new_domain.replace("_", " ").title()
                    final_domain = self.resolve_macro_domain(new_domain, archetype)
                    if meta.get("semantic_title"):
                        final_domain = str(meta["semantic_title"])
                    column_domains[col] = final_domain
                    column_metadata[col]["predicted_domain"] = final_domain
                    domain_scores_all[col][final_domain] = real_conf
                    routing_by_column[col] = {
                        **routing_by_column.get(col, {}),
                        "match_method": "dynamic_cluster",
                        "predicted_domain": final_domain,
                        "display_label": display_label,
                        "is_locked": False,
                        "dynamic_cohesion": round(real_conf, 4),
                    }
                    self.audit.log("dynamic_routing", {"column": col, "status": "dynamic_cluster", "domain": final_domain, "cohesion": round(real_conf, 4)}, step=5)
                else:
                    column_domains[col] = "uncorrelated"
                    column_metadata[col]["predicted_domain"] = "uncorrelated"
                    domain_scores_all[col]["uncorrelated"] = 1.0
                    routing_by_column[col] = {
                        **routing_by_column.get(col, {}),
                        "match_method": "dynamic_cluster",
                        "predicted_domain": "uncorrelated",
                        "display_label": col.replace("_", " ").title(),
                        "is_locked": False,
                    }
                    self.audit.log("dynamic_routing", {"column": col, "status": "uncorrelated_sink"}, step=5)

        self.audit.log("domain_prediction", {col: {"domain": column_domains[col]} for col in columns}, step=6)

        # Clustering Reinforcement (Only on non-locked)
        clusters, cluster_info = self.semantic_clusters.cluster(column_embeddings, column_domains, domain_scores_all)

        for cluster_id, info in cluster_info.items():
            if info["support"] >= 0.6:
                for member in info["members"]:
                    if column_metadata.get(member, {}).get("is_locked", False):
                        continue
                    current_domain = column_domains[member]
                    cluster_domain = info["domain"]
                    if current_domain != cluster_domain:
                        best_score = domain_scores_all[member].get(current_domain, 0)
                        cluster_score = domain_scores_all[member].get(cluster_domain, 0)
                        if best_score - cluster_score < 0.05:
                            column_domains[member] = cluster_domain

        self.schema_graph.build_graph(column_embeddings, clusters, column_domains)

        # Build Explainability Output
        results: dict[str, dict] = {}
        for col in columns:
            routing = routing_by_column.get(col, {})
            match_method = routing.get("match_method", "embedding_similarity")
            is_locked = bool(column_metadata.get(col, {}).get("is_locked", False))

            if is_locked:
                locked_domain = column_metadata[col]["predicted_domain"]
                results[col] = {
                    "normalized_name": normalized[col],
                    "domain": locked_domain,
                    "confidence": 1.0,
                    "top_domain_scores": {locked_domain: 1.0},
                    "cluster_support": 1.0,
                    "graph_consistency": 1.0,
                    "routing_path": match_method,
                    "matched_keyword": routing.get("matched_keyword"),
                    "explainability": {
                        "matching_reason": (
                            f"Assigned '{locked_domain}' by Gatekeeper Phase 1 "
                            f"via {match_method.replace('_', ' ')} "
                            f"(keyword: {routing.get('matched_keyword', 'n/a')})."
                        ),
                        "dataset_archetype": archetype,
                        "match_method": match_method,
                        "is_locked": True,
                    },
                }
                continue

            cluster_support = self.conf_engine.compute_cluster_support(col, column_domains[col], column_domains, clusters)
            graph_consistency = self.conf_engine.compute_graph_consistency(col, column_domains[col], self.schema_graph.edges, column_domains)

            scores = domain_scores_all.get(col, {})
            best_d = column_domains[col]
            top_entries = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
            real_conf = float(scores.get(best_d, 0.0))

            # Ensemble confidence: domain score + cluster support + graph consistency
            ensemble_conf = round(
                0.50 * real_conf + 0.30 * cluster_support + 0.20 * graph_consistency, 4
            )

            results[col] = {
                "normalized_name": normalized[col],
                "domain": best_d,
                "confidence": ensemble_conf,
                "top_domain_scores": dict(top_entries),
                "cluster_support": round(cluster_support, 4),
                "graph_consistency": round(graph_consistency, 4),
                "routing_path": match_method,
                "matched_keyword": routing.get("matched_keyword"),
                "dynamic_cohesion": routing.get("dynamic_cohesion"),
                "explainability": {
                    "matching_reason": (
                        f"Assigned '{best_d}' via {match_method.replace('_', ' ')} "
                        f"(cohesion={routing.get('dynamic_cohesion', 'n/a')}, "
                        f"cluster_support={cluster_support:.3f})."
                    ),
                    "dataset_archetype": archetype,
                    "match_method": match_method,
                    "is_locked": False,
                },
            }

        dependencies = self.priority_mapper.compute_priority(column_embeddings, self.schema_graph, clusters)

        norm_engine = ColumnNormalizationEngine()
        column_normalization = norm_engine.build_plan(
            columns=columns,
            normalized_map=normalized,
            semantic_results=results,
            routing_by_column=routing_by_column,
            column_profiles=column_profiles,
            dataset_archetype=archetype,
        )
        self.audit.log(
            "column_normalization_plan",
            {"rows": column_normalization},
            step=7,
        )

        cluster_output = []
        column_cluster_map: dict[str, str] = {}
        for cluster_id, info in cluster_info.items():
            for m in info["members"]:
                column_cluster_map[m] = cluster_id
            cluster_output.append({
                "cluster_id": cluster_id,
                "domain": info["domain"],
                "support_score": round(float(info.get("support_score", info["support"])), 4),
                "support": round(float(info["support"]), 4),
                "embedding_coherence": round(float(info.get("embedding_coherence", 1.0)), 4),
                "domain_purity": round(float(info.get("domain_purity", info["support"])), 4),
                "avg_domain_confidence": round(float(info.get("avg_domain_confidence", 0.0)), 4),
                "columns": info["members"],
                "domain_distribution": info.get("domain_distribution", {}),
            })

        # Build domain registry for frontend (static ontology + dynamic domains created this run)
        domain_registry = self._build_domain_registry(archetype, dynamic_specs if unknown_columns else {})

        return {
            "dataset_context": {"dataset_type": archetype, "domain_scores": {k: round(v, 4) for k, v in dataset_context_scores.items()}},
            "semantic_mapping": results,
            "column_normalization": column_normalization,
            "domain_registry": domain_registry,
            "clusters": cluster_output,
            "priority_dependencies": dependencies,
            "schema_graph": self.schema_graph.to_dict(),
            "column_cluster_map": column_cluster_map,
            "audit_records": list(self.audit.records),
        }

    def _build_domain_registry(self, archetype: str, dynamic_specs: dict) -> dict:
        """Produce a structured domain registry merging static ontology + this-run dynamic domains."""
        
        # Extract the unique macro domains from your LOCAL_HIERARCHY_MAP
        unique_macro_domains = sorted(list(set(LOCAL_HIERARCHY_MAP.values())))
        
        static_by_type = {
            "macro_categories": {
                "label": "Macro Domains",
                "domains": unique_macro_domains,
                "keywords_sample": {
                    dom: [k for k, v in LOCAL_HIERARCHY_MAP.items() if v == dom][:5]
                    for dom in unique_macro_domains
                }
            }
        }

        dynamic_entries = {}
        for dom_key, spec in (dynamic_specs or {}).items():
            meta = spec.get("metadata", {})
            dynamic_entries[dom_key] = {
                "parent_theme": meta.get("parent_theme", "unknown"),
                "members": meta.get("members", []),
                "cohesion": meta.get("cohesion", 0.0),
                "semantic_title": meta.get("semantic_title"),
                "description": spec.get("description"),
                "keywords": (spec.get("keywords") or [])[:12],
                "is_dynamic": True,
            }

        return {
            "active_archetype": archetype,
            "static_ontology": static_by_type,
            "dynamic_domains": dynamic_entries,
            "universal_domains": ["identifier", "survey_metadata", "geography", "demographic", "household", "uncorrelated_metadata"],
        }

    def _optional_gemini_adjust(self, column: str, combined_scores: dict[str, float], archetype: str):
        try:
            import importlib
            module = importlib.import_module("services.gemini_semantic_fallback")
            apply_gemini_domain_adjustment = getattr(module, "apply_gemini_domain_adjustment")
        except (ImportError, AttributeError):
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