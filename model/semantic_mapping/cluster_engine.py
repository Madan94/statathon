import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy.cluster.hierarchy import linkage, fcluster


class ClusterEngine:

    def __init__(self, similarity_threshold=0.45, min_cluster_size=2):
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size

    def build_similarity_graph(self, embeddings: dict) -> dict:
        columns = list(embeddings.keys())
        vecs = np.array([embeddings[c] for c in columns])
        sim_matrix = cosine_similarity(vecs)

        graph = {}
        for i, col1 in enumerate(columns):
            graph[col1] = {}
            for j, col2 in enumerate(columns):
                if i != j and sim_matrix[i][j] >= self.similarity_threshold:
                    graph[col1][col2] = float(sim_matrix[i][j])
        return graph

    def cluster_columns(self, embeddings: dict) -> dict:
        columns = list(embeddings.keys())
        if len(columns) < 2:
            return {"cluster_0": columns}

        vecs = np.array([embeddings[c] for c in columns])
        distance_matrix = 1.0 - cosine_similarity(vecs)
        np.fill_diagonal(distance_matrix, 0.0)
        distance_matrix = np.clip(distance_matrix, 0.0, None)

        condensed = []
        n = len(columns)
        for i in range(n):
            for j in range(i + 1, n):
                condensed.append(distance_matrix[i][j])
        condensed = np.array(condensed)

        Z = linkage(condensed, method="average")
        labels = fcluster(Z, t=1.0 - self.similarity_threshold, criterion="distance")

        clusters = {}
        for col, label in zip(columns, labels):
            cluster_id = f"cluster_{label}"
            if cluster_id not in clusters:
                clusters[cluster_id] = []
            clusters[cluster_id].append(col)

        return clusters

    def assign_cluster_domains(self, clusters: dict, column_domains: dict) -> dict:
        cluster_domain_map = {}
        for cluster_id, members in clusters.items():
            domain_votes = {}
            for member in members:
                domain = column_domains.get(member, "unknown")
                domain_votes[domain] = domain_votes.get(domain, 0) + 1
            best_domain = max(domain_votes, key=domain_votes.get)
            cluster_domain_map[cluster_id] = {
                "domain": best_domain,
                "support": domain_votes[best_domain] / len(members),
                "members": members
            }
        return cluster_domain_map

    def get_column_cluster(self, column: str, clusters: dict) -> str:
        for cluster_id, members in clusters.items():
            if column in members:
                return cluster_id
        return None
