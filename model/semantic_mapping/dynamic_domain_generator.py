"""
Context-grounded dynamic statistical domains (cohorts of columns).
Generated deterministically from embeddings — no hand-maintained subdomain lists.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity


def _slug_tokens(names: list[str], max_len: int = 8) -> str:
    raw = "_".join(sorted(names))[:200]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return digest


class DynamicDomainGenerator:
    """
    For each embedding cohort (within provisional parent domain), register a runtime domain
    whose description is anchored on dataset archetype + member column semantics.
    """

    def __init__(self, max_dynamic_domains: int = 24, min_cluster_size: int = 1):
        self.max_dynamic_domains = max_dynamic_domains
        self.min_cluster_size = min_cluster_size

    def generate(
        self,
        dataset_type: str,
        normalized_columns: dict[str, str],
        column_embeddings: dict[str, np.ndarray],
        provisional_domains: dict[str, str],
        schema_graph=None,
        dataset_domain: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        columns = list(normalized_columns.keys())
        if not columns:
            return {}

        names = list(normalized_columns.items())
        embedder_vecs = np.stack([column_embeddings[c] for c in columns])
        n = len(columns)
        k = min(self.max_dynamic_domains, max(1, n // 2 or 1))

        if n == 1:
            labels = np.array([0])
        else:
            # 🚨 FIX: Do not force n_clusters. Use a strict distance_threshold.
            # 0.25 cosine distance means they must be at least 75% similar to cluster.
            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=0.25, 
                metric="cosine",
                linkage="average",
            )
            labels = clustering.fit_predict(embedder_vecs)

        groups: dict[int, list[str]] = {}
        for col, lab in zip(columns, labels):
            groups.setdefault(int(lab), []).append(col)

        runtime: dict[str, dict[str, Any]] = {}
        sim_mat = cosine_similarity(embedder_vecs)
        col_index = {c: i for i, c in enumerate(columns)}

        for lab, members in groups.items():
            if len(members) < self.min_cluster_size:
                continue
            parent_votes: dict[str, int] = {}
            for m in members:
                p = provisional_domains.get(m, "general")
                parent_votes[p] = parent_votes.get(p, 0) + 1
            parent_mode = max(parent_votes, key=parent_votes.get)

            intra_sims = []
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    intra_sims.append(float(sim_mat[col_index[a]][col_index[b]]))
            cohesion = float(np.mean(intra_sims)) if intra_sims else 1.0

            slug = _slug_tokens(members)
            domain_key = f"dyn_{parent_mode}_{slug}"
            member_labels = [normalized_columns[m] for m in members]
            
            # --- CONTEXT ENRICHMENT ---
            # Inject context prefix if the user provided one
            context_prefix = f"[{dataset_domain}] " if dataset_domain else ""
            desc = (
                f"{context_prefix}Official statistics variables grouped under dataset archetype '{dataset_type}' "
                f"with provisional theme '{parent_mode}'. "
                f"Co-occurring measures: {', '.join(member_labels[:12])}"
                f"{' …' if len(member_labels) > 12 else ''}. "
                f"Embedding cohesion={cohesion:.3f}."
            )
            tokens = set()
            for lbl in member_labels:
                tokens.update(re.findall(r"[a-z0-9]+", lbl.lower()))
            keywords = sorted(tokens)[:40]

            runtime[domain_key] = {
                "description": desc,
                "keywords": keywords,
                "metadata": {
                    "parent_theme": parent_mode,
                    "members": members,
                    "cohesion": round(cohesion, 4),
                    "cohort_label": lab,
                },
            }
        return runtime
