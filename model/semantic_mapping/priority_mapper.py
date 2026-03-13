import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class PriorityMapper:

    def __init__(self, max_influencers=5):
        self.max_influencers = max_influencers

    def compute_priority(self, embeddings, schema_graph, clusters):
        columns = list(embeddings.keys())
        dependencies = {}

        centrality = schema_graph.compute_centrality()

        for target in columns:
            scores = []

            graph_neighbors = schema_graph.get_neighbors(target)
            propagated = schema_graph.propagate_influence(target, max_depth=2, decay=0.5)

            for source in columns:
                if source == target:
                    continue

                emb_sim = self._embedding_similarity(embeddings[target], embeddings[source])

                cluster_strength = 0.2 if self._same_cluster(target, source, clusters) else 0.0

                graph_weight = graph_neighbors.get(source, 0.0)
                prop_weight = propagated.get(source, 0.0)
                graph_signal = max(graph_weight, prop_weight)

                influence = (
                    0.50 * emb_sim
                    + 0.30 * cluster_strength
                    + 0.20 * graph_signal
                )

                if influence > 0.15:
                    scores.append({
                        "column": source,
                        "score": round(float(influence), 4),
                        "embedding_similarity": round(float(emb_sim), 4),
                        "cluster_strength": round(float(cluster_strength), 4),
                        "graph_signal": round(float(graph_signal), 4),
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