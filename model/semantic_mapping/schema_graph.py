import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class SchemaGraph:

    def __init__(self, edge_threshold=0.3):
        self.edge_threshold = edge_threshold
        self.nodes = []
        self.edges = {}
        self.node_attributes = {}

    def build_graph(self, embeddings: dict, clusters: dict, column_domains: dict):
        self.nodes = list(embeddings.keys())

        for col in self.nodes:
            self.node_attributes[col] = {
                "domain": column_domains.get(col, "unknown"),
                "cluster": self._find_cluster(col, clusters)
            }

        columns = list(embeddings.keys())
        vecs = np.array([embeddings[c] for c in columns])
        sim_matrix = cosine_similarity(vecs)

        self.edges = {}
        for i, col1 in enumerate(columns):
            self.edges[col1] = {}
            for j, col2 in enumerate(columns):
                if i == j:
                    continue

                emb_sim = float(sim_matrix[i][j])
                cluster_bonus = 0.2 if self._same_cluster(col1, col2, clusters) else 0.0
                domain_bonus = 0.1 if column_domains.get(col1) != column_domains.get(col2) else 0.0

                edge_weight = emb_sim + cluster_bonus + domain_bonus
                edge_weight = min(edge_weight, 1.0)

                if edge_weight >= self.edge_threshold:
                    self.edges[col1][col2] = round(edge_weight, 4)

    def get_neighbors(self, column: str) -> dict:
        return self.edges.get(column, {})

    def get_top_neighbors(self, column: str, top_k: int = 5) -> list:
        neighbors = self.edges.get(column, {})
        sorted_n = sorted(neighbors.items(), key=lambda x: x[1], reverse=True)
        return sorted_n[:top_k]

    def compute_centrality(self) -> dict:
        centrality = {}
        for node in self.nodes:
            neighbors = self.edges.get(node, {})
            centrality[node] = sum(neighbors.values()) / max(len(self.nodes) - 1, 1)
        return centrality

    def propagate_influence(self, source: str, max_depth: int = 2, decay: float = 0.5) -> dict:
        influence = {}
        frontier = {source: 1.0}

        for depth in range(max_depth):
            next_frontier = {}
            for node, score in frontier.items():
                neighbors = self.edges.get(node, {})
                for neighbor, weight in neighbors.items():
                    if neighbor == source:
                        continue
                    propagated = score * weight * decay
                    if neighbor in influence:
                        influence[neighbor] = max(influence[neighbor], propagated)
                    else:
                        influence[neighbor] = propagated
                    if neighbor not in next_frontier or next_frontier[neighbor] < propagated:
                        next_frontier[neighbor] = propagated
            frontier = next_frontier

        return influence

    def to_dict(self) -> dict:
        edge_list = []
        seen = set()
        for src, neighbors in self.edges.items():
            for tgt, weight in neighbors.items():
                key = tuple(sorted([src, tgt]))
                if key not in seen:
                    seen.add(key)
                    edge_list.append({
                        "source": src,
                        "target": tgt,
                        "weight": weight
                    })
        return {
            "nodes": [{"name": n, **self.node_attributes.get(n, {})} for n in self.nodes],
            "edges": edge_list
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
