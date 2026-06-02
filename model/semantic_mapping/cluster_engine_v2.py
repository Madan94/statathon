"""High-accuracy clustering layer.

Sits on top of the existing `cluster_engine.py` without replacing it. Three
mechanisms drive accuracy:

  1. DOMAIN-AWARE DISTANCE
     Hybrid distance = (1 - cosine_similarity) + lambda * domain_mismatch_penalty
     Columns with the same inferred semantic domain are pulled together;
     columns with different domains are pushed apart. The legacy
     embedding-only path remains as the fallback.

  2. QUALITY-DRIVEN RE-CLUSTERING
     Try (method, params) combinations and keep the result whose silhouette
     is highest. Stops early when silhouette >= 0.6 (no point continuing).

  3. CLUSTER-DOMAIN ALIGNMENT
     A separate quality metric — V-measure between assigned clusters and
     domain labels. Surfaces in the output so the user / pipeline can see
     how well semantic and structural clustering agree.

Public entry point: `cluster_columns_v2(embeddings, column_domains=None,
                                          target_silhouette=0.55)`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .cluster_engine import ClusterEngine
from .cluster_quality import evaluate_clusters, semantic_cluster_name

logger = logging.getLogger(__name__)


@dataclass
class ClusterRun:
    method: str
    params: dict[str, Any]
    clusters: dict[str, list[str]]
    quality: dict[str, Any]
    domain_alignment: dict[str, Any] | None = None
    semantic_names: dict[str, str] = field(default_factory=dict)


def cluster_columns_v2(
    embeddings: dict[str, np.ndarray],
    *,
    column_domains: dict[str, str] | None = None,
    target_silhouette: float = 0.55,
    lambda_domain: float = 0.35,
    candidate_methods: tuple[str, ...] = ("hdbscan", "hierarchical"),
    similarity_thresholds: tuple[float, ...] = (0.45, 0.55, 0.65),
) -> dict[str, Any]:
    """Try several configurations, pick the one with highest silhouette.

    Returns:
        {
            "clusters":           best cluster -> [member columns],
            "method":             "hdbscan" | "hierarchical",
            "params":             chosen parameters,
            "quality":            silhouette / davies_bouldin / calinski / per-cluster,
            "domain_alignment":   V-measure between clusters and domain labels,
            "semantic_names":     human-readable name per cluster,
            "candidates":         all attempted runs (for audit),
        }
    """
    columns = list(embeddings.keys())
    if len(columns) < 2:
        return _trivial_output(columns)

    # ---- Build hybrid embedding if domains are available ----
    hybrid_embeddings = embeddings
    if column_domains:
        hybrid_embeddings = _domain_aware_embeddings(
            embeddings, column_domains, lambda_domain
        )

    runs: list[ClusterRun] = []

    for method in candidate_methods:
        if method == "hdbscan":
            for min_cluster_size in (2, 3):
                try:
                    engine = ClusterEngine(min_cluster_size=min_cluster_size)
                    # Force hdbscan path via env hack would be ugly; instead call _cluster_hdbscan directly
                    vecs = np.array([hybrid_embeddings[c] for c in columns]).astype(float)
                    clusters = engine._cluster_hdbscan(columns, vecs)
                    if not clusters:
                        continue
                    quality = evaluate_clusters(clusters, embeddings)  # quality on original embeddings
                    runs.append(ClusterRun(
                        method=f"hdbscan",
                        params={"min_cluster_size": min_cluster_size,
                                "domain_aware": column_domains is not None},
                        clusters=clusters,
                        quality=quality,
                    ))
                except Exception as exc:
                    logger.debug("hdbscan run failed: %s", exc)
                    continue

        elif method == "hierarchical":
            for thr in similarity_thresholds:
                try:
                    engine = ClusterEngine(similarity_threshold=thr)
                    # Pin the threshold without env juggling
                    import os
                    prev = os.environ.get("STATATHON_LINKAGE_SIMILARITY")
                    os.environ["STATATHON_LINKAGE_SIMILARITY"] = str(thr)
                    try:
                        os.environ["STATATHON_CLUSTERING"] = "hierarchical"
                        clusters = engine.cluster_columns(hybrid_embeddings)
                    finally:
                        if prev is None:
                            os.environ.pop("STATATHON_LINKAGE_SIMILARITY", None)
                        else:
                            os.environ["STATATHON_LINKAGE_SIMILARITY"] = prev
                        os.environ.pop("STATATHON_CLUSTERING", None)
                    if not clusters:
                        continue
                    quality = evaluate_clusters(clusters, embeddings)
                    runs.append(ClusterRun(
                        method="hierarchical",
                        params={"similarity_threshold": thr,
                                "domain_aware": column_domains is not None},
                        clusters=clusters,
                        quality=quality,
                    ))
                    if (quality.get("silhouette") or 0) >= target_silhouette:
                        # Early exit — we hit the target
                        pass  # still try a couple more for safety
                except Exception as exc:
                    logger.debug("hierarchical run failed: %s", exc)

    if not runs:
        # Last resort: legacy single call
        engine = ClusterEngine()
        clusters = engine.cluster_columns(embeddings)
        quality = evaluate_clusters(clusters, embeddings)
        runs.append(ClusterRun(method="legacy", params={}, clusters=clusters, quality=quality))

    # ---- Score each run and pick the best ----
    if column_domains:
        for r in runs:
            r.domain_alignment = _cluster_domain_alignment(r.clusters, column_domains)

    best = max(runs, key=_run_score)

    # Semantic naming on the winner
    semantic_names = {
        cid: semantic_cluster_name(members, column_domains)
        for cid, members in best.clusters.items()
    }
    best.semantic_names = semantic_names

    # Rename clusters in the output to their semantic names (de-dup if collisions)
    renamed: dict[str, list[str]] = {}
    seen: set[str] = set()
    for cid, members in best.clusters.items():
        new_id = semantic_names.get(cid, cid)
        # Disambiguate collisions
        suffix = 0
        candidate = new_id
        while candidate in seen:
            suffix += 1
            candidate = f"{new_id}_{suffix}"
        renamed[candidate] = members
        seen.add(candidate)
        semantic_names[cid] = candidate

    return {
        "clusters": renamed,
        "method": best.method,
        "params": best.params,
        "quality": best.quality,
        "domain_alignment": best.domain_alignment,
        "semantic_names": semantic_names,
        "candidates": [
            {
                "method": r.method,
                "params": r.params,
                "silhouette": r.quality.get("silhouette"),
                "davies_bouldin": r.quality.get("davies_bouldin"),
                "verdict": r.quality.get("verdict"),
                "domain_alignment_v_measure": (
                    r.domain_alignment.get("v_measure") if r.domain_alignment else None
                ),
                "cluster_count": len(r.clusters),
            }
            for r in runs
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _domain_aware_embeddings(
    embeddings: dict[str, np.ndarray],
    column_domains: dict[str, str],
    lambda_domain: float,
) -> dict[str, np.ndarray]:
    """Append a domain-one-hot block to each embedding so the distance metric
    naturally pulls same-domain columns together."""
    columns = list(embeddings.keys())
    domains = sorted({column_domains.get(c, "__none__") for c in columns})
    dom_to_idx = {d: i for i, d in enumerate(domains)}
    block_dim = len(domains)
    scale = float(lambda_domain) * np.linalg.norm(
        next(iter(embeddings.values()))
    )

    out: dict[str, np.ndarray] = {}
    for c in columns:
        vec = np.asarray(embeddings[c], dtype=float)
        ext = np.zeros(block_dim, dtype=float)
        d = column_domains.get(c)
        if d in dom_to_idx:
            ext[dom_to_idx[d]] = scale
        out[c] = np.concatenate([vec, ext])
    return out


def _cluster_domain_alignment(clusters: dict[str, list[str]],
                               column_domains: dict[str, str]) -> dict[str, Any]:
    """How well do clusters align with the domain assignments?"""
    columns = []
    cluster_labels = []
    domain_labels = []
    for cidx, (_, members) in enumerate(clusters.items()):
        for m in members:
            if m in column_domains:
                columns.append(m)
                cluster_labels.append(cidx)
                domain_labels.append(column_domains[m])
    if len(set(domain_labels)) < 2 or len(set(cluster_labels)) < 2:
        return {"v_measure": None, "homogeneity": None, "completeness": None}
    try:
        from sklearn.metrics import (
            v_measure_score, homogeneity_score, completeness_score,
            adjusted_rand_score,
        )
        v = float(v_measure_score(domain_labels, cluster_labels))
        h = float(homogeneity_score(domain_labels, cluster_labels))
        cs = float(completeness_score(domain_labels, cluster_labels))
        ari = float(adjusted_rand_score(domain_labels, cluster_labels))
        return {
            "v_measure": round(v, 4),
            "homogeneity": round(h, 4),
            "completeness": round(cs, 4),
            "adjusted_rand_index": round(ari, 4),
            "verdict": (
                "excellent" if v >= 0.85
                else "good" if v >= 0.65
                else "fair" if v >= 0.40
                else "poor"
            ),
        }
    except Exception as exc:
        logger.info("Domain alignment metrics failed: %s", exc)
        return {"v_measure": None, "error": str(exc)}


def _run_score(run: ClusterRun) -> float:
    """Combined score across silhouette + domain-alignment + cluster count sanity."""
    q = run.quality or {}
    sil = q.get("silhouette") or 0.0
    db = q.get("davies_bouldin") or 1.5
    # Lower DB is better; convert to 0..1 (clip)
    db_inv = max(0.0, 1.0 - min(db, 3.0) / 3.0)

    score = 0.5 * (sil + 1.0) / 2.0  # silhouette in [-1,1] -> [0,1]
    score += 0.25 * db_inv

    if run.domain_alignment and run.domain_alignment.get("v_measure") is not None:
        score += 0.25 * float(run.domain_alignment["v_measure"])

    # Penalise degenerate clusterings
    n_clusters = len(run.clusters)
    total_members = sum(len(m) for m in run.clusters.values())
    if n_clusters <= 1:
        score *= 0.5
    if total_members and max(len(m) for m in run.clusters.values()) >= 0.85 * total_members:
        # one mega-cluster
        score *= 0.7

    return score


def _trivial_output(columns: list[str]) -> dict[str, Any]:
    return {
        "clusters": {"cluster_0": columns},
        "method": "trivial",
        "params": {},
        "quality": {"verdict": "single_cluster"},
        "domain_alignment": None,
        "semantic_names": {"cluster_0": "all_columns"},
        "candidates": [],
    }
