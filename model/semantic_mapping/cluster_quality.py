"""Cluster quality + stability + semantic naming.

Plug-in module that operates on the output of ClusterEngine.cluster_columns
without changing the existing call sites. Two public entry points:

  * evaluate_clusters(clusters, embeddings) -> dict
        Returns silhouette, Davies-Bouldin, Calinski-Harabasz scores, per-cluster
        cohesion, and an overall quality verdict.

  * stability_score(embeddings, n_resamples=10, frac=0.85) -> float
        Adjusted Rand Index across resampled clusterings; 1.0 = perfectly stable.

  * semantic_cluster_name(members, column_domains) -> str
        Picks a meaningful name like 'demographic_age_group' instead of
        'cluster_hdbscan_3'.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------


def evaluate_clusters(clusters: dict[str, list[str]],
                       embeddings: dict[str, np.ndarray]) -> dict[str, Any]:
    """Per-cluster + overall quality metrics."""
    if not clusters or len(clusters) < 2:
        return {
            "silhouette": None,
            "davies_bouldin": None,
            "calinski_harabasz": None,
            "per_cluster": {},
            "verdict": "single_cluster" if clusters else "empty",
        }

    columns: list[str] = []
    labels: list[int] = []
    for label_id, (cluster_id, members) in enumerate(clusters.items()):
        for m in members:
            if m in embeddings:
                columns.append(m)
                labels.append(label_id)

    if not columns:
        return {"silhouette": None, "verdict": "no_embeddings", "per_cluster": {}}

    X = np.vstack([np.asarray(embeddings[c]) for c in columns])
    y = np.asarray(labels)
    unique = np.unique(y)
    if unique.size < 2:
        return {
            "silhouette": None,
            "davies_bouldin": None,
            "calinski_harabasz": None,
            "verdict": "degenerate",
            "per_cluster": {},
        }

    sil = db = ch = None
    try:
        from sklearn.metrics import (
            silhouette_score,
            davies_bouldin_score,
            calinski_harabasz_score,
        )
        sil = float(silhouette_score(X, y, metric="cosine"))
        db = float(davies_bouldin_score(X, y))
        ch = float(calinski_harabasz_score(X, y))
    except Exception as exc:
        logger.info("sklearn metrics unavailable: %s", exc)

    # Per-cluster cohesion: mean intra-cluster cosine similarity
    per_cluster: dict[str, dict[str, Any]] = {}
    for cluster_id, members in clusters.items():
        vecs = [embeddings[m] for m in members if m in embeddings]
        if len(vecs) < 2:
            per_cluster[cluster_id] = {"cohesion": None, "size": len(members)}
            continue
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            sims = cosine_similarity(np.vstack(vecs))
            # Take upper triangle off-diagonal
            iu = np.triu_indices(sims.shape[0], k=1)
            cohesion = float(sims[iu].mean()) if iu[0].size else None
        except Exception:
            cohesion = None
        per_cluster[cluster_id] = {"cohesion": cohesion, "size": len(members)}

    # Verdict heuristic
    verdict = "unknown"
    if sil is not None:
        if sil >= 0.5:
            verdict = "strong"
        elif sil >= 0.25:
            verdict = "reasonable"
        elif sil >= 0.1:
            verdict = "weak"
        else:
            verdict = "poor"

    return {
        "silhouette": sil,
        "davies_bouldin": db,
        "calinski_harabasz": ch,
        "verdict": verdict,
        "per_cluster": per_cluster,
    }


# ---------------------------------------------------------------------------
# Stability via ARI on resampled subsets
# ---------------------------------------------------------------------------


def stability_score(embeddings: dict[str, np.ndarray],
                     cluster_fn,
                     n_resamples: int = 10,
                     frac: float = 0.85,
                     rng_seed: int = 42) -> dict[str, Any]:
    """Adjusted Rand Index across resampled clusterings.

    `cluster_fn(embeddings_subdict) -> clusters` is any clustering callable
    that returns the same shape as ClusterEngine.cluster_columns.
    """
    cols = list(embeddings.keys())
    n = len(cols)
    if n < 6:
        return {"stability_ari": None, "verdict": "too_small", "samples": 0}

    rng = np.random.default_rng(rng_seed)

    # Reference clustering on full data
    try:
        ref = cluster_fn(embeddings)
    except Exception as exc:
        return {"stability_ari": None, "verdict": "ref_failed", "error": str(exc)}
    ref_labels = _labels_for(cols, ref)

    aris: list[float] = []
    sample_size = max(3, int(n * frac))
    try:
        from sklearn.metrics import adjusted_rand_score
    except Exception:
        return {"stability_ari": None, "verdict": "sklearn_missing"}

    for _ in range(n_resamples):
        idx = rng.choice(n, size=sample_size, replace=False)
        sub_cols = [cols[i] for i in idx]
        sub_emb = {c: embeddings[c] for c in sub_cols}
        try:
            sub_clusters = cluster_fn(sub_emb)
            sub_labels = _labels_for(sub_cols, sub_clusters)
            # Align by intersecting columns
            ref_sub = [ref_labels[cols.index(c)] for c in sub_cols]
            aris.append(float(adjusted_rand_score(ref_sub, sub_labels)))
        except Exception:
            continue

    if not aris:
        return {"stability_ari": None, "verdict": "all_resamples_failed"}

    mean_ari = float(np.mean(aris))
    verdict = (
        "stable" if mean_ari >= 0.7
        else "moderate" if mean_ari >= 0.4
        else "unstable"
    )
    return {
        "stability_ari": mean_ari,
        "stability_std": float(np.std(aris)),
        "verdict": verdict,
        "samples": len(aris),
    }


def _labels_for(columns: list[str], clusters: dict[str, list[str]]) -> list[int]:
    cluster_id_to_label = {cid: idx for idx, cid in enumerate(clusters.keys())}
    out: list[int] = []
    for c in columns:
        assigned = -1
        for cid, members in clusters.items():
            if c in members:
                assigned = cluster_id_to_label[cid]
                break
        out.append(assigned)
    return out


# ---------------------------------------------------------------------------
# Semantic naming
# ---------------------------------------------------------------------------


def semantic_cluster_name(members: list[str],
                           column_domains: dict[str, str] | None = None,
                           max_tokens: int = 3) -> str:
    """Build a human-readable cluster name from its members.

    Strategy:
      1. If 70%+ of members share a semantic domain, use `<domain>_<topic>`.
      2. Otherwise extract the most common informative token across member names.
      3. Fall back to first member's name if no signal is present.
    """
    if not members:
        return "empty_cluster"

    # 1) Dominant semantic domain
    domain_part: str | None = None
    if column_domains:
        domains = [column_domains.get(m, "").strip() for m in members]
        domains = [d for d in domains if d]
        if domains:
            cnt = Counter(domains)
            top, top_n = cnt.most_common(1)[0]
            if top_n / len(domains) >= 0.7 and top.lower() not in {"unknown", ""}:
                domain_part = top.lower().replace(" ", "_")

    # 2) Most common informative token
    stop = {
        "the", "of", "in", "for", "and", "or", "a", "an", "by", "on", "to",
        "is", "are", "id", "code", "key", "value", "amount",
    }
    token_counts: Counter[str] = Counter()
    import re
    for m in members:
        for tok in re.findall(r"[a-z0-9]+", m.lower()):
            if tok in stop or len(tok) <= 1:
                continue
            token_counts[tok] += 1
    top_tokens = [tok for tok, _ in token_counts.most_common(max_tokens)]

    if domain_part and top_tokens:
        # Avoid duplicating the domain word in topic part
        topic_tokens = [t for t in top_tokens if t != domain_part]
        return f"{domain_part}_{'_'.join(topic_tokens[:2])}" if topic_tokens else domain_part
    if top_tokens:
        return "_".join(top_tokens[:2])
    if domain_part:
        return domain_part
    # 3) Fallback
    return re.sub(r"[^a-z0-9_]+", "_", members[0].lower())[:40]
