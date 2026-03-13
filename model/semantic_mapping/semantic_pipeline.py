from semantic_mapping.column_preprocessor import ColumnPreprocessor
from semantic_mapping.bert_embedder import BertEmbedder
from semantic_mapping.domain_repository import DomainRepository
from semantic_mapping.similarity_engine import SimilarityEngine
from semantic_mapping.confidence_engine import ConfidenceEngine
from semantic_mapping.priority_mapper import PriorityMapper
from semantic_mapping.cluster_engine import ClusterEngine
from semantic_mapping.schema_graph import SchemaGraph
from semantic_mapping.context_inference import ContextInference
from storage.vector_store import VectorStore
from audit.audit_logger import AuditLogger


class SemanticPipeline:

    def __init__(self):
        self.vector_store = VectorStore()
        self.preprocessor = ColumnPreprocessor()
        self.embedder = BertEmbedder(vector_store=self.vector_store)
        self.domain_repo = DomainRepository()
        self.sim_engine = SimilarityEngine()
        self.conf_engine = ConfidenceEngine()
        self.priority_mapper = PriorityMapper()
        self.cluster_engine = ClusterEngine()
        self.schema_graph = SchemaGraph()
        self.context_engine = ContextInference(self.embedder)
        self.audit = AuditLogger()

    def run(self, columns):
        self.audit.clear()

        # Step 1: Column Preprocessing
        normalized = self.preprocessor.normalize_columns(columns)
        column_tokens = {col: self.preprocessor.extract_tokens(col) for col in columns}
        self.audit.log("column_normalization", {
            "columns": normalized
        }, step=1)

        # Step 2: Embedding Generation (batch)
        column_embeddings = self.embedder.embed_dict(normalized)
        self.audit.log("embedding_generation", {
            "columns_embedded": list(column_embeddings.keys()),
            "embedding_dim": len(next(iter(column_embeddings.values())))
        }, step=2)

        # Step 3: Domain Embedding Generation
        domain_descriptions = self.domain_repo.get_domain_descriptions()
        domain_embeddings = self.embedder.embed_batch(list(domain_descriptions.values()))
        domain_embeddings = {
            name: domain_embeddings[desc]
            for name, desc in domain_descriptions.items()
        }

        # Step 4: Dataset Context Inference
        column_texts = list(normalized.values())
        dataset_context_scores = self.context_engine.infer_dataset_context(column_texts)
        dataset_context = max(dataset_context_scores, key=dataset_context_scores.get)
        self.audit.log("context_inference", {
            "dataset_context": dataset_context,
            "context_scores": dataset_context_scores
        }, step=4)

        # Step 5: Multi-Signal Domain Classification
        column_domains = {}
        domain_scores_all = {}
        for col in columns:
            emb = column_embeddings[col]

            # Signal 1: Embedding similarity
            embedding_scores = self.sim_engine.compute_domain_similarity(emb, domain_embeddings)

            # Signal 2: Keyword boost
            tokens = column_tokens[col]
            keyword_boost = {}
            for domain_name in self.domain_repo.get_domain_names():
                keywords = self.domain_repo.get_domain_keywords(domain_name)
                keyword_boost[domain_name] = self.sim_engine.compute_keyword_boost(tokens, keywords)

            # Signal 3: Context boost
            context_boost = self.context_engine.get_context_boost(tokens, dataset_context)

            # Combine signals
            combined_scores = self.context_engine.compute_domain_scores_with_context(
                embedding_scores, keyword_boost, context_boost
            )
            domain_scores_all[col] = combined_scores

            best_domain = max(combined_scores, key=combined_scores.get)
            column_domains[col] = best_domain

        self.audit.log("domain_prediction", {
            col: {"domain": column_domains[col], "scores": domain_scores_all[col]}
            for col in columns
        }, step=5)

        # Step 6: Column Clustering
        clusters = self.cluster_engine.cluster_columns(column_embeddings)
        cluster_info = self.cluster_engine.assign_cluster_domains(clusters, column_domains)

        # Cluster reinforcement: if cluster majority disagrees, override weak assignments
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

        self.audit.log("clustering", {
            "clusters": {cid: info for cid, info in cluster_info.items()},
            "column_domains_after_reinforcement": column_domains
        }, step=6)

        # Step 7: Schema Graph Construction
        self.schema_graph.build_graph(column_embeddings, clusters, column_domains)
        self.audit.log("schema_graph", {
            "node_count": len(self.schema_graph.nodes),
            "edge_count": sum(len(v) for v in self.schema_graph.edges.values()) // 2
        }, step=7)

        # Step 8: Confidence Scoring (multi-signal)
        results = {}
        for col in columns:
            cluster_support = self.conf_engine.compute_cluster_support(
                col, column_domains[col], column_domains, clusters
            )
            graph_consistency = self.conf_engine.compute_graph_consistency(
                col, column_domains[col], self.schema_graph.edges, column_domains
            )
            confidence = self.conf_engine.calculate_confidence(
                domain_scores_all[col],
                cluster_support=cluster_support,
                graph_consistency=graph_consistency
            )
            results[col] = {
                "normalized_name": normalized[col],
                "domain": column_domains[col],
                "confidence": confidence,
                "top_domain_scores": dict(
                    sorted(domain_scores_all[col].items(), key=lambda x: x[1], reverse=True)[:3]
                ),
                "cluster_support": round(cluster_support, 4),
                "graph_consistency": round(graph_consistency, 4),
            }

        self.audit.log("confidence_scoring", {
            col: {"confidence": results[col]["confidence"],
                  "cluster_support": results[col]["cluster_support"],
                  "graph_consistency": results[col]["graph_consistency"]}
            for col in columns
        }, step=8)

        # Step 9: Priority Dependency Inference (graph-based, no hardcoding)
        dependencies = self.priority_mapper.compute_priority(
            column_embeddings, self.schema_graph, clusters
        )
        self.audit.log("dependency_inference", {
            col: deps for col, deps in dependencies.items()
        }, step=9)

        # Build output
        cluster_output = []
        for cluster_id, info in cluster_info.items():
            cluster_output.append({
                "cluster_id": cluster_id,
                "domain": info["domain"],
                "support": round(info["support"], 4),
                "columns": info["members"]
            })

        return {
            "dataset_context": {
                "inferred_type": dataset_context,
                "context_scores": {k: round(v, 4) for k, v in dataset_context_scores.items()}
            },
            "semantic_mapping": results,
            "clusters": cluster_output,
            "priority_dependencies": dependencies,
            "schema_graph": self.schema_graph.to_dict()
        }