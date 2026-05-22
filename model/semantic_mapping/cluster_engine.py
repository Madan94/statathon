import os

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy.cluster.hierarchy import linkage, fcluster


class ClusterEngine:
    """Column embedding clustering — hierarchical average-linkage default, optional HDBSCAN."""

    def __init__(self, similarity_threshold=0.45, min_cluster_size=2):
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size

    def _effective_linkage_similarity(self, n_columns: int) -> float:
        """
        For tiny tables, use a higher cosine bar so hierarchical linkage splits more cleanly
        (avoids one mega-cluster after semantic merge passes). Controlled by env.
        """
        try:
            base = float(os.getenv("STATATHON_LINKAGE_SIMILARITY", str(self.similarity_threshold)))
        except ValueError:
            base = self.similarity_threshold
        base = max(0.05, min(base, 0.92))

        try:
            small_max = int(os.getenv("STATATHON_SMALL_DATASET_MAX_COLS", "24"))
        except ValueError:
            small_max = 24

        if n_columns <= small_max and n_columns >= 2:
            try:
                bump = float(os.getenv("STATATHON_LINKAGE_SIMILARITY_SMALL", "0.58"))
            except ValueError:
                bump = 0.58
            bump = max(0.05, min(bump, 0.92))
            merged = max(base, bump)
        else:
            merged = base
        try:
            cap = float(os.getenv("STATATHON_LINKAGE_SIMILARITY_CAP", "0.88"))
            merged = min(merged, cap)
        except ValueError:
            merged = min(merged, 0.88)
        return merged

    def build_similarity_graph(self, embeddings: dict) -> dict:
        columns = list(embeddings.keys())
        thr = self._effective_linkage_similarity(len(columns))
        vecs = np.array([embeddings[c] for c in columns])
        sim_matrix = cosine_similarity(vecs)

        graph = {}
        for i, col1 in enumerate(columns):
            graph[col1] = {}
            for j, col2 in enumerate(columns):
                if i != j and sim_matrix[i][j] >= thr:
                    graph[col1][col2] = float(sim_matrix[i][j])
        return graph

    def _cluster_hdbscan(self, columns: list[str], vecs: np.ndarray) -> dict[str, list[str]]:
        import hdbscan

        n = len(columns)
        try:
            small_max = int(os.getenv("STATATHON_SMALL_DATASET_MAX_COLS", "24"))
        except ValueError:
            small_max = 24

        # Tiny datasets: favour smaller minimum cluster sizes so columns can split logically.
        if n <= small_max:
            default_floor = max(2, min(5, max(2, (n + 2) // 4)))
            try:
                min_sz = max(
                    self.min_cluster_size,
                    int(os.getenv("STATATHON_HDBSCAN_MIN_CLUSTER_SMALL", str(default_floor))),
                )
            except ValueError:
                min_sz = max(self.min_cluster_size, default_floor)
        else:
            min_sz = max(
                self.min_cluster_size,
                min(12, max(2, n // max(n // 25, 1))),
            )
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_sz,
            min_samples=max(1, min_sz // 3),
            metric="euclidean",
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(vecs)
        clusters: dict[str, list[str]] = {}
        for col, lbl in zip(columns, labels):
            if int(lbl) < 0:
                key = "hdbscan_outlier_" + str(col).replace(" ", "_")[:240]
                clusters[key] = [col]
                continue
            key = f"cluster_hdbscan_{int(lbl)}"
            clusters.setdefault(key, []).append(col)
        for k in list(clusters.keys()):
            if k.startswith("cluster_hdbscan_"):
                clusters[k] = sorted(clusters[k])
        return clusters

    def cluster_columns(self, embeddings: dict) -> dict:
        columns = list(embeddings.keys())
        if len(columns) < 2:
            return {"cluster_0": columns}

        vecs = np.array([embeddings[c] for c in columns])

        mode = (os.getenv("STATATHON_CLUSTERING") or "hierarchical").strip().lower()
        if mode == "hdbscan":
            try:
                return self._cluster_hdbscan(columns, vecs.astype(float))
            except ImportError:
                pass

        distance_matrix = 1.0 - cosine_similarity(vecs)
        np.fill_diagonal(distance_matrix, 0.0)
        distance_matrix = np.clip(distance_matrix, 0.0, None)

        condensed = []
        n = len(columns)
        for i in range(n):
            for j in range(i + 1, n):
                condensed.append(distance_matrix[i][j])
        condensed = np.array(condensed)

        thr = self._effective_linkage_similarity(n)
        Z = linkage(condensed, method="average")
        labels = fcluster(Z, t=1.0 - thr, criterion="distance")

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
                "members": members,
            }
        return cluster_domain_map

    def get_column_cluster(self, column: str, clusters: dict) -> str | None:
        for cluster_id, members in clusters.items():
            if column in members:
                return cluster_id
        return None
