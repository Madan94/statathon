import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class SchemaGraph:
    """Column relation graph with explicit edge semantics for audit persistence."""

    def __init__(self, edge_threshold=0.3):
        self.edge_threshold = edge_threshold
        self.nodes: list[str] = []
        self.edges: dict[str, dict[str, dict]] = {}
        self.node_attributes: dict[str, dict] = {}

    @staticmethod
    def edge_weight(edge_data) -> float:
        if isinstance(edge_data, dict):
            return float(edge_data.get("weight", 0.0))
        return float(edge_data)

    def build_graph(self, embeddings: dict, clusters: dict, column_domains: dict):
        self.nodes = list(embeddings.keys())

        for col in self.nodes:
            self.node_attributes[col] = {
                "domain": column_domains.get(col, "unknown"),
                "cluster": self._find_cluster(col, clusters),
            }

        columns = list(embeddings.keys())
        vecs = np.array([embeddings[c] for c in columns])
        sim_matrix = cosine_similarity(vecs)

        self.edges = {c: {} for c in columns}
        for i, col1 in enumerate(columns):
            for j, col2 in enumerate(columns):
                if i == j:
                    continue

                emb_sim = float(sim_matrix[i][j])
                same_cl = self._same_cluster(col1, col2, clusters)
                cluster_bonus = 0.18 if same_cl else 0.0
                cross_domain = column_domains.get(col1) != column_domains.get(col2)
                domain_bonus = 0.08 if cross_domain else 0.05

                edge_weight = min(emb_sim + cluster_bonus + domain_bonus, 1.0)

                if edge_weight < self.edge_threshold:
                    continue

                if same_cl and emb_sim >= 0.35:
                    rel = "co_cluster_semantic"
                    reason = (
                        f"High embedding similarity ({emb_sim:.3f}) within same cluster; "
                        f"coherence bonus {cluster_bonus:.3f}."
                    )
                elif cross_domain:
                    rel = "cross_domain_linkage"
                    reason = (
                        f"Cross-domain statistical linkage: {column_domains.get(col1)} ↔ "
                        f"{column_domains.get(col2)}; similarity={emb_sim:.3f}, graph_bonus={domain_bonus:.3f}."
                    )
                else:
                    rel = "intra_domain_association"
                    reason = (
                        f"Same domain ({column_domains.get(col1)}), similarity={emb_sim:.3f}; "
                        "potential redundant or complementary measures."
                    )

                payload = {
                    "weight": round(edge_weight, 4),
                    "relationship_type": rel,
                    "semantic_reason": reason,
                    "embedding_similarity": round(emb_sim, 4),
                    "cluster_adjacency": same_cl,
                }
                self.edges[col1][col2] = payload

    def neighbor_weights(self, column: str) -> dict[str, float]:
        out = {}
        for neigh, data in self.edges.get(column, {}).items():
            out[neigh] = self.edge_weight(data)
        return out

    def get_neighbors(self, column: str) -> dict:
        return self.edges.get(column, {})

    def get_top_neighbors(self, column: str, top_k: int = 5) -> list:
        neighbors = self.neighbor_weights(column)
        sorted_n = sorted(neighbors.items(), key=lambda x: x[1], reverse=True)
        return sorted_n[:top_k]

    def compute_centrality(self) -> dict:
        centrality = {}
        for node in self.nodes:
            neighbors = self.edges.get(node, {})
            total_w = sum(self.edge_weight(v) for v in neighbors.values())
            centrality[node] = total_w / max(len(self.nodes) - 1, 1)
        return centrality

    def propagate_influence(self, source: str, max_depth: int = 2, decay: float = 0.5) -> dict:
        influence = {}
        frontier = {source: 1.0}

        for _depth in range(max_depth):
            next_frontier = {}
            for node, score in frontier.items():
                neighbors = self.edges.get(node, {})
                for neighbor, edge_data in neighbors.items():
                    if neighbor == source:
                        continue
                    w = self.edge_weight(edge_data)
                    propagated = score * w * decay
                    influence[neighbor] = max(influence.get(neighbor, 0.0), propagated)
                    next_frontier[neighbor] = max(next_frontier.get(neighbor, 0.0), propagated)
            frontier = next_frontier
            if not frontier:
                break

        return influence

    def to_dict(self) -> dict:
        edge_list = []
        seen = set()
        for src, neighbors in self.edges.items():
            for tgt, data in neighbors.items():
                key = tuple(sorted([src, tgt]))
                if key in seen:
                    continue
                seen.add(key)
                w = self.edge_weight(data)
                rel = data.get("relationship_type", "semantic") if isinstance(data, dict) else "semantic"
                reason = data.get("semantic_reason", "") if isinstance(data, dict) else ""
                edge_list.append(
                    {
                        "source": src,
                        "target": tgt,
                        "weight": w,
                        "relationship_type": rel,
                        "semantic_reason": reason,
                    }
                )
        return {
            "nodes": [{"name": n, **self.node_attributes.get(n, {})} for n in self.nodes],
            "edges": edge_list,
        }

    def _find_cluster(self, column, clusters):
        for cluster_id, members in clusters.items():
            if column in members:
                return cluster_id
        return None

    def _same_cluster(self, col1, col2, clusters):
        for members in clusters.values():
            if col1 in members and col2 in members:
                return True
        return False
