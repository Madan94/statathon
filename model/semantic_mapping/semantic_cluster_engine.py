"""
Semantic clustering with domain and similarity reinforcement beyond raw cosine buckets.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from semantic_mapping.cluster_engine import ClusterEngine


class SemanticClusterEngine:
    """
    Wraps hierarchical clustering, then refines boundaries using domain affinity
    and embedding coherence so clusters align with statistical themes.
    """

    def __init__(
        self,
        base: ClusterEngine | None = None,
        coherence_merge_threshold: float = 0.72,
    ):
        self._base = base or ClusterEngine()
        self.coherence_merge_threshold = coherence_merge_threshold

    def cluster(
        self,
        column_embeddings: dict[str, np.ndarray],
        column_domains: dict[str, str],
        domain_scores_all: dict[str, dict[str, float]],
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
        n = len(column_embeddings)
        try:
            small_max = int(os.getenv("STATATHON_SMALL_DATASET_MAX_COLS", "24"))
        except ValueError:
            small_max = 24

        skip_merge_small = (
            os.getenv("STATATHON_SKIP_CLUSTER_MERGE_SMALL", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )

        clusters = self._base.cluster_columns(column_embeddings)
        if skip_merge_small and n <= small_max:
            # Cross-cluster coherence merge destroys separation on skinny survey tables (~10 cols).
            pass
        else:
            clusters = self._refine_clusters(column_embeddings, clusters, column_domains)
        cluster_info = self._assign_with_support(clusters, column_domains, domain_scores_all)
        return clusters, cluster_info

    def _refine_clusters(
        self,
        embeddings: dict[str, np.ndarray],
        clusters: dict[str, list[str]],
        column_domains: dict[str, str],
    ) -> dict[str, list[str]]:
        cols = list(embeddings.keys())
        if len(cols) < 2:
            return clusters

        vecs = np.stack([embeddings[c] for c in cols])
        sim = cosine_similarity(vecs)
        idx = {c: i for i, c in enumerate(cols)}

        members_by_cluster = {k: set(v) for k, v in clusters.items()}
        merged = True
        while merged:
            merged = False
            cluster_ids = list(members_by_cluster.keys())
            for i, ci in enumerate(cluster_ids):
                for cj in cluster_ids[i + 1 :]:
                    mi, mj = members_by_cluster[ci], members_by_cluster[cj]
                    if not mi or not mj:
                        continue
                    cross = [
                        sim[idx[a]][idx[b]]
                        for a in mi
                        for b in mj
                    ]
                    mean_cross = float(np.mean(cross)) if cross else 0.0
                    dom_i = {column_domains.get(x, "") for x in mi}
                    dom_j = {column_domains.get(x, "") for x in mj}
                    domain_overlap = len(dom_i & dom_j) > 0
                    if mean_cross >= self.coherence_merge_threshold or (
                        mean_cross >= 0.55 and domain_overlap
                    ):
                        members_by_cluster[ci] = mi | mj
                        members_by_cluster.pop(cj, None)
                        merged = True
                        break
                if merged:
                    break

        out: dict[str, list[str]] = {}
        for new_id, (old_id, members) in enumerate(sorted(members_by_cluster.items(), key=lambda x: x[0])):
            out[f"cluster_{new_id}"] = sorted(members)
        return out

    def _assign_with_support(
        self,
        clusters: dict[str, list[str]],
        column_domains: dict[str, str],
        domain_scores_all: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, Any]]:
        info: dict[str, dict[str, Any]] = {}
        for cluster_id, members in clusters.items():
            votes: dict[str, int] = {}
            for m in members:
                d = column_domains.get(m, "unknown")
                votes[d] = votes.get(d, 0) + 1
            best_domain = max(votes, key=votes.get)
            plurality = votes[best_domain] / max(len(members), 1)

            score_mass = 0.0
            for m in members:
                scores = domain_scores_all.get(m, {})
                score_mass += float(scores.get(best_domain, 0.0))
            concentration = score_mass / max(len(members), 1)

            support_score = round(0.6 * plurality + 0.4 * concentration, 4)

            info[cluster_id] = {
                "domain": best_domain,
                "support": plurality,
                "support_score": support_score,
                "members": members,
                "domain_distribution": votes,
            }
        return info
