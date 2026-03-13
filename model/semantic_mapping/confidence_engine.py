class ConfidenceEngine:

    @staticmethod
    def calculate_confidence(
        similarity_scores: dict,
        cluster_support: float = 0.0,
        graph_consistency: float = 0.0
    ) -> float:
        sorted_scores = sorted(similarity_scores.values(), reverse=True)
        best = sorted_scores[0]
        second = sorted_scores[1] if len(sorted_scores) > 1 else 0.0

        margin = best - second

        embedding_signal = 0.5 * best + 0.5 * margin

        confidence = (
            0.50 * embedding_signal
            + 0.30 * cluster_support
            + 0.20 * graph_consistency
        )

        confidence = max(0.0, min(confidence, 1.0))
        return round(confidence, 4)

    @staticmethod
    def compute_cluster_support(column: str, assigned_domain: str, cluster_domains: dict, clusters: dict) -> float:
        for cluster_id, members in clusters.items():
            if column in members:
                same_domain = sum(1 for m in members if cluster_domains.get(m) == assigned_domain)
                return same_domain / len(members)
        return 0.0

    @staticmethod
    def compute_graph_consistency(column: str, assigned_domain: str, neighbors: dict, column_domains: dict) -> float:
        col_neighbors = neighbors.get(column, {})
        if not col_neighbors:
            return 0.0
        consistent = 0
        total = 0
        for neighbor, weight in col_neighbors.items():
            total += weight
            neighbor_domain = column_domains.get(neighbor, "")
            if neighbor_domain == assigned_domain:
                consistent += weight
        return consistent / total if total > 0 else 0.0