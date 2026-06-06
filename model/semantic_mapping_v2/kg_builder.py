"""
Schema Graph + Knowledge Graph builder for Semantic Mapping V2.

Two artefacts are produced from the pipeline output:

1. SCHEMA GRAPH — columns are nodes; edges carry explicit OWL/RDF relationship
   semantics derived from embedding similarity, cluster adjacency and domain
   agreement (audit-friendly, same edge vocabulary as v1 but rebuilt cleanly
   on the V2 vectors).

2. KNOWLEDGE GRAPH — a typed, hierarchical graph:
       (Dataset)-[:HAS_USECASE]->(Usecase)
       (Usecase)-[:DEFINES_DOMAIN]->(Domain)
       (Domain)-[:GROUPED_AS]->(Cluster)
       (Cluster)-[:CONTAINS]->(Column)
       (Column)-[:MAPPED_TO]->(Domain)
       (Column)-[:RELATED_TO {weight, owl_type}]->(Column)
   Optionally synced to Neo4j when NEO4J_ENABLED is set; degrades to an
   in-memory dict otherwise.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema graph
# ---------------------------------------------------------------------------
class SchemaGraphV2:
    """Column relation graph with OWL/RDF edge semantics (V2)."""

    def __init__(self, edge_threshold: float = 0.30):
        self.edge_threshold = edge_threshold
        self.nodes: list[str] = []
        self.node_attributes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, dict[str, Any]]] = {}

    def build(
        self,
        embeddings: dict[str, np.ndarray],
        column_domains: dict[str, str],
        column_clusters: dict[str, str],
    ) -> "SchemaGraphV2":
        self.nodes = list(embeddings.keys())
        for col in self.nodes:
            self.node_attributes[col] = {
                "domain": column_domains.get(col, "unknown"),
                "cluster": column_clusters.get(col),
            }
        self.edges = {c: {} for c in self.nodes}
        if len(self.nodes) < 2:
            return self

        matrix = np.vstack([self._unit(embeddings[c]) for c in self.nodes])
        sim = matrix @ matrix.T  # cosine on L2-normalized rows

        for i, col1 in enumerate(self.nodes):
            for j in range(i + 1, len(self.nodes)):
                col2 = self.nodes[j]
                emb_sim = float(sim[i, j])
                same_cluster = (
                    column_clusters.get(col1) is not None
                    and column_clusters.get(col1) == column_clusters.get(col2)
                )
                d1 = column_domains.get(col1, "unknown")
                d2 = column_domains.get(col2, "unknown")
                cross_domain = d1 != d2

                cluster_bonus = 0.18 if same_cluster else 0.0
                domain_bonus = 0.08 if cross_domain else 0.05
                weight = min(emb_sim + cluster_bonus + domain_bonus, 1.0)
                if weight < self.edge_threshold:
                    continue

                rel, owl_type, owl_label, reason = self._classify(
                    emb_sim, same_cluster, cross_domain, d1, d2, cluster_bonus, domain_bonus
                )
                payload = {
                    "weight": round(weight, 4),
                    "relationship_type": rel,
                    "owl_type": owl_type,
                    "owl_label": owl_label,
                    "semantic_reason": reason,
                    "embedding_similarity": round(emb_sim, 4),
                    "cluster_adjacency": same_cluster,
                    "source_domain": d1,
                    "target_domain": d2,
                }
                self.edges[col1][col2] = payload
        return self

    @staticmethod
    def _classify(emb_sim, same_cluster, cross_domain, d1, d2, cluster_bonus, domain_bonus):
        if same_cluster and emb_sim >= 0.35:
            rel = "co_cluster_semantic"
            if d1 == d2:
                owl_type, owl_label = "owl:equivalentProperty", "Equivalent measure"
            else:
                owl_type, owl_label = "owl:ObjectProperty", "Co-cluster semantic link"
            reason = (
                f"High similarity ({emb_sim:.3f}) within same cluster; "
                f"coherence bonus {cluster_bonus:.3f}."
            )
        elif cross_domain:
            rel = "cross_domain_linkage"
            owl_type, owl_label = "owl:ObjectProperty", "Cross-domain linkage"
            reason = f"Cross-domain linkage {d1} <-> {d2}; similarity={emb_sim:.3f}."
        elif emb_sim >= 0.55:
            rel = "intra_domain_association"
            owl_type, owl_label = "rdfs:subPropertyOf", "Intra-domain sub-property"
            reason = f"Same domain ({d1}), similarity={emb_sim:.3f}."
        else:
            rel = "intra_domain_association"
            owl_type, owl_label = "rdfs:seeAlso", "Related measure"
            reason = f"Same domain ({d1}), similarity={emb_sim:.3f}."
        return rel, owl_type, owl_label, reason

    @staticmethod
    def _unit(v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v

    def to_dict(self) -> dict[str, Any]:
        edge_list: list[dict[str, Any]] = []
        for src, neighbors in self.edges.items():
            for tgt, data in neighbors.items():
                edge_list.append({"source": src, "target": tgt, **data})
        return {
            "nodes": [{"name": n, **self.node_attributes.get(n, {})} for n in self.nodes],
            "edges": edge_list,
        }


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------
class KnowledgeGraphBuilder:
    """Builds the typed hierarchical KG and optionally syncs it to Neo4j."""

    def build(
        self,
        *,
        dataset_id: str,
        dataset_name: str,
        usecase: str,
        usecase_confidence: float,
        domains: dict[str, dict[str, Any]],
        mappings: dict[str, Any],
        clusters: list[Any],
        column_clusters: dict[str, str],
        schema_graph: SchemaGraphV2 | None = None,
    ) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        ds_id = f"dataset::{dataset_id}"
        uc_id = f"usecase::{usecase}"
        nodes.append({"id": ds_id, "label": "Dataset", "name": dataset_name})
        nodes.append({"id": uc_id, "label": "Usecase", "name": usecase,
                      "confidence": round(usecase_confidence, 4)})
        edges.append({"source": ds_id, "target": uc_id, "type": "HAS_USECASE"})

        # Domain nodes.
        domain_node_id: dict[str, str] = {}
        for name, meta in domains.items():
            nid = f"domain::{name}"
            domain_node_id[name] = nid
            nodes.append({
                "id": nid, "label": "Domain", "name": name,
                "domain_type": meta.get("domain_type", "static"),
                "description": meta.get("description", ""),
            })
            edges.append({"source": uc_id, "target": nid, "type": "DEFINES_DOMAIN"})

        # Cluster nodes.
        for cl in clusters:
            cl_d = cl.to_dict() if hasattr(cl, "to_dict") else cl
            cid = f"cluster::{cl_d['cluster_id']}"
            nodes.append({
                "id": cid, "label": "Cluster", "name": cl_d["cluster_name"],
                "dominant_domain": cl_d["dominant_domain"],
                "purity": cl_d["purity"],
                "cluster_confidence": cl_d["cluster_confidence"],
            })
            dom = cl_d["dominant_domain"]
            if dom in domain_node_id:
                edges.append({"source": domain_node_id[dom], "target": cid, "type": "GROUPED_AS"})

        # Column nodes + edges.
        for col, m in mappings.items():
            m_d = m.to_dict() if hasattr(m, "to_dict") else m
            col_id = f"column::{col}"
            nodes.append({
                "id": col_id, "label": "Column", "name": col,
                "domain": m_d["domain"], "confidence": m_d["confidence"],
                "source": m_d["source"], "dtype": m_d.get("dtype", ""),
            })
            if m_d["domain"] in domain_node_id:
                edges.append({
                    "source": col_id, "target": domain_node_id[m_d["domain"]],
                    "type": "MAPPED_TO", "confidence": m_d["confidence"],
                })
            cl_id = column_clusters.get(col)
            if cl_id:
                edges.append({"source": f"cluster::{cl_id}", "target": col_id, "type": "CONTAINS"})

        # Column-to-column relations from the schema graph.
        if schema_graph is not None:
            for src, neighbors in schema_graph.edges.items():
                for tgt, data in neighbors.items():
                    edges.append({
                        "source": f"column::{src}", "target": f"column::{tgt}",
                        "type": "RELATED_TO", "weight": data["weight"],
                        "owl_type": data["owl_type"],
                        "relationship_type": data["relationship_type"],
                    })

        kg = {
            "dataset_id": dataset_id,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "domain_count": len(domain_node_id),
                "cluster_count": len(clusters),
                "column_count": len(mappings),
            },
        }
        kg["neo4j_synced"] = self._sync_neo4j(kg)
        return kg

    # -- optional Neo4j sync -------------------------------------------------
    def _sync_neo4j(self, kg: dict[str, Any]) -> bool:
        try:
            from graph.settings import Neo4jSettings
        except Exception:  # noqa: BLE001
            return False
        settings = Neo4jSettings.from_env()
        if not settings.enabled or not settings.password:
            return False
        try:
            from graph.neo4j_client import neo4j_driver

            driver = neo4j_driver(settings)
        except Exception as exc:  # noqa: BLE001
            logger.info("Neo4j sync skipped (driver unavailable): %s", exc)
            return False

        ds = kg["dataset_id"]
        try:
            with driver.session(database=settings.database) as session:
                session.run(
                    "MATCH (n {dataset_id: $ds}) DETACH DELETE n", ds=ds
                )
                for node in kg["nodes"]:
                    props = {k: v for k, v in node.items() if k not in {"id", "label"}}
                    props["dataset_id"] = ds
                    session.run(
                        f"MERGE (n:`{self._safe_label(node['label'])}` {{id: $id}}) SET n += $props",
                        id=node["id"], props=props,
                    )
                for edge in kg["edges"]:
                    props = {k: v for k, v in edge.items() if k not in {"source", "target", "type"}}
                    session.run(
                        "MATCH (a {id: $s}), (b {id: $t}) "
                        f"MERGE (a)-[r:`{self._safe_label(edge['type'])}`]->(b) SET r += $props",
                        s=edge["source"], t=edge["target"], props=props,
                    )
            logger.info("Neo4j sync complete for dataset %s", ds)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j sync failed: %s", exc)
            return False
        finally:
            try:
                driver.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _safe_label(label: str) -> str:
        return "".join(c for c in str(label) if c.isalnum() or c == "_") or "Node"
