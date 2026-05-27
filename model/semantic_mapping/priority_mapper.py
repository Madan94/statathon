import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class PriorityMapper:

    def __init__(self, max_influencers=5):
        self.max_influencers = max_influencers

    def compute_priority(self, embeddings, schema_graph, clusters):
        columns = list(embeddings.keys())
        dependencies = {}

        for target in columns:
            scores = []

            graph_neighbors = schema_graph.get_neighbors(target)
            propagated = schema_graph.propagate_influence(target, max_depth=2, decay=0.5)

            for source in columns:
                if source == target:
                    continue

                emb_sim = self._embedding_similarity(embeddings[target], embeddings[source])

                cluster_strength = 0.2 if self._same_cluster(target, source, clusters) else 0.0

                raw_gw = graph_neighbors.get(source)
                if isinstance(raw_gw, dict):
                    graph_weight = float(raw_gw.get("weight", 0.0))
                else:
                    graph_weight = float(raw_gw or 0.0)

                prop_weight = float(propagated.get(source, 0.0))
                graph_signal = max(graph_weight, prop_weight)

                influence = (
                    0.50 * emb_sim
                    + 0.30 * cluster_strength
                    + 0.20 * graph_signal
                )

                if influence > 0.15:
                    dependency_reason = (
                        f"Influence={influence:.3f}: embedding_sim={emb_sim:.3f}, "
                        f"cluster_strength={cluster_strength:.3f}, graph_signal={graph_signal:.3f} "
                        f"(edge_weight={graph_weight:.3f}, propagated={prop_weight:.3f})."
                    )
                    scores.append({
                        "column": source,
                        "score": round(float(influence), 4),
                        "embedding_similarity": round(float(emb_sim), 4),
                        "cluster_strength": round(float(cluster_strength), 4),
                        "graph_signal": round(float(graph_signal), 4),
                        "dependency_reason": dependency_reason,
                    })

            scores.sort(key=lambda x: x["score"], reverse=True)
            dependencies[target] = scores[:self.max_influencers]

        return dependencies

    @staticmethod
    def _embedding_similarity(vec1, vec2):
        v1 = np.asarray(vec1).reshape(1, -1)
        v2 = np.asarray(vec2).reshape(1, -1)
        return float(cosine_similarity(v1, v2)[0][0])

    @staticmethod
    def _same_cluster(col1, col2, clusters):
        for members in clusters.values():
            if col1 in members and col2 in members:
                return True
        return False