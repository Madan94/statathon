import json
import os
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
from semantic_mapping.hierarchical_router import HierarchicalDomainRouter
from storage.vector_store import VectorStore
from audit.audit_logger import AuditLogger
from sentence_transformers import SentenceTransformer

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
    "household": "household",
    "uncorrelated_metadata": "uncorrelated"
}


class SemanticPipeline:

    def __init__(self, vector_cache_dir: str | None = None):
        repo_root = Path(__file__).resolve().parents[2]
        cache = vector_cache_dir or str(repo_root / "model" / "storage" / "vector_cache")
        self.vector_store = VectorStore(cache_dir=cache)
        self.preprocessor = ColumnPreprocessor()
        self.domain_repo = DomainRepository()

        custom_weights = os.getenv("MOSPI_EMBEDDING_MODEL_PATH")
        default_weights = repo_root / "model" / "weights" / "mospi-minilm-v1"
        
        if custom_weights:
            model_path = custom_weights
        elif default_weights.exists():
            model_path = str(default_weights)
        else:
            print("WARNING: Custom MoSPI weights not found. Falling back to base model.")
            model_path = "sentence-transformers/all-MiniLM-L6-v2"

        print(f"Loading Bi-Encoder from: {model_path}")
        self.encoder_model = SentenceTransformer(model_path)
        
        self.embedder = BertEmbedder(model=self.encoder_model, vector_store=self.vector_store)
        
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
        
        # 2. Dynamic Heuristic (Categorize dynamic domains by their prefix)
        if domain_name.startswith("dyn_"):
            parts = domain_name.split('_')
            valid_archetypes = {"labor", "health", "education", "agriculture", "census", "economic_industry"}
            if len(parts) > 1 and parts[1] in valid_archetypes:
                return parts[1]
                
        # 3. Final Fallback
        return dataset_archetype or domain_name

    def run(self, columns: list[str], dataset_domain: str = None, column_enrichment: dict[str, str] | None = None) -> dict:
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
                "schema_graph": {"nodes": [], "edges": []}, "column_cluster_map": {}, "audit_records": list(self.audit.records),
            }

        self.audit.log("dataset_context_inferencer", {"dataset_type": archetype}, step=3)

        # Tracking State
        column_domains: dict[str, str] = {}
        domain_scores_all: dict[str, dict[str, float]] = {}
        column_metadata: dict[str, dict[str, object]] = {}
        
        locked_columns = []
        unknown_columns = []
        
        # ==========================================
        # PHASE 1: THE GATEKEEPER (Static Ontology Dominance)
        # ==========================================
        STRICT_THRESHOLD = 0.85 

        for col in columns:
            emb = column_embeddings[col]
            
            prediction = self.hierarchical_router.predict_domain(col, emb, archetype)
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
                provisional_domains={}, # Empty to force intrinsic naming
                dataset_domain=dataset_domain,
            )
            self.domain_repo.merge_runtime(dynamic_specs)

            dyn_mapping = {}
            for dom_key, spec in dynamic_specs.items():
                for member in spec.get("metadata", {}).get("members", []):
                    dyn_mapping[member] = dom_key

            # ==========================================
            # PHASE 3: THE UNCORRELATED SINK
            # ==========================================
            for col in unknown_columns:
                new_domain = dyn_mapping.get(col)
                if new_domain:
                    # Dynamic Assignment Success
                    final_domain = self.resolve_macro_domain(new_domain, archetype)
                    column_domains[col] = final_domain
                    column_metadata[col]["predicted_domain"] = final_domain
                    domain_scores_all[col][final_domain] = 0.80 # Assign dynamic baseline confidence
                    self.audit.log("dynamic_routing", {"column": col, "status": "dynamic_cluster", "domain": final_domain}, step=5)
                else:
                    # Safety Net Failure
                    column_domains[col] = "uncorrelated"
                    column_metadata[col]["predicted_domain"] = "uncorrelated"
                    domain_scores_all[col]["uncorrelated"] = 1.0
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
            if column_metadata.get(col, {}).get("is_locked", False):
                locked_domain = column_metadata[col]["predicted_domain"]
                results[col] = {
                    "normalized_name": normalized[col],
                    "domain": locked_domain,
                    "confidence": 1.0,
                    "top_domain_scores": {locked_domain: 1.0},
                    "cluster_support": 1.0,
                    "graph_consistency": 1.0,
                    "explainability": {
                        "matching_reason": f"Assigned '{locked_domain}' by Gatekeeper Phase 1 (Static Ontology Lock).",
                        "dataset_archetype": archetype,
                    },
                }
                continue

            cluster_support = self.conf_engine.compute_cluster_support(col, column_domains[col], column_domains, clusters)
            graph_consistency = self.conf_engine.compute_graph_consistency(col, column_domains[col], self.schema_graph.edges, column_domains)
            
            scores = domain_scores_all.get(col, {})
            best_d = column_domains[col]
            top_entries = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
            
            results[col] = {
                "normalized_name": normalized[col],
                "domain": best_d,
                "confidence": round(float(scores.get(best_d, 0.8)), 4),
                "top_domain_scores": dict(top_entries),
                "cluster_support": round(cluster_support, 4),
                "graph_consistency": round(graph_consistency, 4),
                "explainability": {
                    "matching_reason": f"Assigned '{best_d}' by Gatekeeper Phase 2 (Dynamic Fallback).",
                    "dataset_archetype": archetype,
                },
            }

        dependencies = self.priority_mapper.compute_priority(column_embeddings, self.schema_graph, clusters)

        cluster_output = []
        column_cluster_map: dict[str, str] = {}
        for cluster_id, info in cluster_info.items():
            for m in info["members"]:
                column_cluster_map[m] = cluster_id
            cluster_output.append({
                "cluster_id": cluster_id, "domain": info["domain"],
                "support_score": round(float(info.get("support_score", info["support"])), 4),
                "support": round(float(info["support"]), 4), "columns": info["members"],
                "domain_distribution": info.get("domain_distribution", {}),
            })

        return {
            "dataset_context": {"dataset_type": archetype, "domain_scores": {k: round(v, 4) for k, v in dataset_context_scores.items()}},
            "semantic_mapping": results,
            "clusters": cluster_output,
            "priority_dependencies": dependencies,
            "schema_graph": self.schema_graph.to_dict(),
            "column_cluster_map": column_cluster_map,
            "audit_records": list(self.audit.records),
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