"""
STEP 9-11 — Domain Clustering, Cluster Labeling, Cluster Validation.

Runs only AFTER semantic mapping completes. For each column a composite feature
vector is built and L2-normalized:

    40% semantic embedding   (the column's query vector)
    25% domain mapping       (one-hot over mapped domains)
    15% sample values        (hashed value-token signature)
    10% statistics           (numeric profile: log-mean, std, skew, range)
    10% column type          (one-hot over dtype)

HDBSCAN (scikit-learn native) groups the columns. Noise points (label -1) are
each given a singleton cluster so every column is placed. Clusters are labeled
by majority domain vote (STEP 10) and validated by purity; clusters below the
purity bar are split by domain (STEP 11) so mixed clusters are avoided.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from semantic_mapping_v2.config import (
    CLUSTER_FEATURE_WEIGHTS,
    CLUSTER_PURITY_THRESHOLD,
    HDBSCAN_MIN_CLUSTER_SIZE,
    HDBSCAN_MIN_SAMPLES,
)
from semantic_mapping_v2.feature_extraction import ColumnFeature
from semantic_mapping_v2.matching_engine import ColumnMapping

logger = logging.getLogger(__name__)


@dataclass
class Cluster:
    cluster_id: str
    cluster_name: str
    cluster_confidence: float
    columns: list[str] = field(default_factory=list)
    dominant_domain: str = ""
    purity: float = 0.0
    domain_distribution: dict[str, float] = field(default_factory=dict)
    embedding_coherence: float = 0.0
    avg_domain_confidence: float = 0.0
    explainability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "cluster_confidence": round(self.cluster_confidence, 4),
            "columns": self.columns,
            "dominant_domain": self.dominant_domain,
            "purity": round(self.purity, 4),
            "domain_purity": round(self.purity, 4),
            "domain_distribution": {k: round(v, 4) for k, v in self.domain_distribution.items()},
            "embedding_coherence": round(self.embedding_coherence, 4),
            "avg_domain_confidence": round(self.avg_domain_confidence, 4),
            "explainability": self.explainability,
        }


class DomainClusteringEngine:
    def __init__(
        self,
        *,
        min_cluster_size: int = HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples: int = HDBSCAN_MIN_SAMPLES,
        purity_threshold: float = CLUSTER_PURITY_THRESHOLD,
    ):
        self.min_cluster_size = max(2, min_cluster_size)
        self.min_samples = max(1, min_samples)
        self.purity_threshold = purity_threshold

    def cluster(
        self,
        *,
        features: dict[str, ColumnFeature],
        mappings: dict[str, ColumnMapping],
        column_vectors: dict[str, np.ndarray],
        df: Any | None = None,
        schema_edges: list[dict[str, Any]] | None = None,
    ) -> tuple[list[Cluster], dict[str, str]]:
        columns = [c for c in features if c in column_vectors]
        if not columns:
            return [], {}
        if len(columns) == 1:
            cl = self._singleton(columns[0], mappings, column_vectors)
            return [cl], {columns[0]: cl.cluster_id}

        graph_neighbors = self._embedding_neighbors(column_vectors, columns)
        if schema_edges:
            graph_neighbors = self._merge_schema_neighbors(graph_neighbors, schema_edges, columns)

        matrix = self._build_feature_matrix(
            columns,
            features,
            mappings,
            column_vectors,
            df=df,
            graph_neighbors=graph_neighbors,
        )
        labels = self._run_hdbscan(matrix)
        groups = self._labels_to_groups(columns, labels)

        clusters = self._label_and_validate(groups, mappings, column_vectors)
        col_to_cluster: dict[str, str] = {}
        for cl in clusters:
            for c in cl.columns:
                col_to_cluster[c] = cl.cluster_id
        return clusters, col_to_cluster

    # -- STEP 9: feature matrix ---------------------------------------------
    def _build_feature_matrix(
        self,
        columns: list[str],
        features: dict[str, ColumnFeature],
        mappings: dict[str, ColumnMapping],
        column_vectors: dict[str, np.ndarray],
        *,
        df: Any | None = None,
        graph_neighbors: dict[str, list[tuple[str, float]]] | None = None,
    ) -> np.ndarray:
        domain_list = sorted({mappings[c].domain for c in columns})
        domain_index = {d: i for i, d in enumerate(domain_list)}
        dtype_list = sorted({features[c].dtype for c in columns})
        dtype_index = {d: i for i, d in enumerate(dtype_list)}
        graph_neighbors = graph_neighbors or {}

        w = CLUSTER_FEATURE_WEIGHTS
        rows: list[np.ndarray] = []
        for c in columns:
            emb = self._unit(np.asarray(column_vectors[c], dtype=np.float32)) * w["embedding"]

            dom = np.zeros(len(domain_index), dtype=np.float32)
            dom[domain_index[mappings[c].domain]] = 1.0
            dom = self._unit(dom) * w["domain"]

            samp = self._sample_signature(features[c]) * w["sample_values"]
            stat = self._stat_vector(features[c]) * w["statistics"]

            typ = np.zeros(len(dtype_index), dtype=np.float32)
            typ[dtype_index[features[c].dtype]] = 1.0
            typ = self._unit(typ) * w["column_type"]

            graph = self._graph_affinity_vector(c, graph_neighbors) * w.get("graph_affinity", 0.0)
            corr = self._correlation_vector(c, columns, df) * w.get("correlation", 0.0)

            rows.append(np.concatenate([emb, dom, samp, stat, typ, graph, corr]))
        return np.vstack(rows).astype(np.float32)

    @staticmethod
    def _unit(v: np.ndarray) -> np.ndarray:
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v

    def _sample_signature(self, feat: ColumnFeature, dim: int = 16) -> np.ndarray:
        vec = np.zeros(dim, dtype=np.float32)
        for v in feat.samples:
            for tok in str(v).lower().split():
                vec[hash(tok) % dim] += 1.0
        return self._unit(vec)

    def _stat_vector(self, feat: ColumnFeature, dim: int = 5) -> np.ndarray:
        vec = np.zeros(dim, dtype=np.float32)
        if feat.dtype == "numeric" and feat.statistics:
            s = feat.statistics
            vec[0] = math.copysign(math.log1p(abs(s.get("mean", 0.0))), s.get("mean", 0.0))
            vec[1] = math.log1p(abs(s.get("std", 0.0)))
            vec[2] = float(s.get("skew", 0.0))
            rng = abs(s.get("max", 0.0) - s.get("min", 0.0))
            vec[3] = math.log1p(rng)
            vec[4] = 1.0
        else:
            vec[4] = float(min(feat.cardinality, 100)) / 100.0
        return self._unit(vec)

    def _embedding_neighbors(
        self,
        column_vectors: dict[str, np.ndarray],
        columns: list[str],
        *,
        k: int = 3,
    ) -> dict[str, list[tuple[str, float]]]:
        neighbors: dict[str, list[tuple[str, float]]] = {}
        for col in columns:
            vec = self._unit(np.asarray(column_vectors[col], dtype=np.float32))
            scores: list[tuple[str, float]] = []
            for other in columns:
                if other == col:
                    continue
                other_vec = self._unit(np.asarray(column_vectors[other], dtype=np.float32))
                scores.append((other, float(np.dot(vec, other_vec))))
            scores.sort(key=lambda item: item[1], reverse=True)
            neighbors[col] = scores[:k]
        return neighbors

    @staticmethod
    def _merge_schema_neighbors(
        neighbors: dict[str, list[tuple[str, float]]],
        schema_edges: list[dict[str, Any]],
        columns: list[str],
    ) -> dict[str, list[tuple[str, float]]]:
        merged = {col: list(items) for col, items in neighbors.items()}
        col_set = set(columns)
        for edge in schema_edges:
            src = str(edge.get("source") or edge.get("source_column") or "")
            tgt = str(edge.get("target") or edge.get("target_column") or "")
            if src not in col_set or tgt not in col_set or src == tgt:
                continue
            weight = float(edge.get("weight") or edge.get("edge_weight") or 0.5)
            for a, b in ((src, tgt), (tgt, src)):
                bucket = merged.setdefault(a, [])
                if not any(n == b for n, _ in bucket):
                    bucket.append((b, weight))
                bucket.sort(key=lambda item: item[1], reverse=True)
                merged[a] = bucket[:5]
        return merged

    def _graph_affinity_vector(
        self,
        column: str,
        neighbors: dict[str, list[tuple[str, float]]],
        dim: int = 8,
    ) -> np.ndarray:
        vec = np.zeros(dim, dtype=np.float32)
        for idx, (_, weight) in enumerate(neighbors.get(column, [])[:dim]):
            vec[idx] = max(0.0, float(weight))
        return self._unit(vec)

    def _correlation_vector(
        self,
        column: str,
        columns: list[str],
        df: Any | None,
        dim: int = 8,
    ) -> np.ndarray:
        vec = np.zeros(dim, dtype=np.float32)
        if df is None or column not in getattr(df, "columns", []):
            return vec
        try:
            import pandas as pd
        except ImportError:  # pragma: no cover
            return vec

        numeric_cols = [
            c for c in columns
            if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
        ]
        if column not in numeric_cols or len(numeric_cols) < 2:
            return vec

        sample = df[numeric_cols].head(500)
        corrs: list[tuple[str, float]] = []
        for other in numeric_cols:
            if other == column:
                continue
            pair = sample[[column, other]].dropna()
            if len(pair) < 3:
                continue
            corr = pair[column].corr(pair[other])
            if corr is not None and np.isfinite(corr):
                corrs.append((other, abs(float(corr))))
        corrs.sort(key=lambda item: item[1], reverse=True)
        for idx, (_, corr) in enumerate(corrs[:dim]):
            vec[idx] = corr
        return self._unit(vec)

    def _embedding_coherence(
        self,
        members: list[str],
        column_vectors: dict[str, np.ndarray],
    ) -> float:
        if len(members) < 2:
            return 1.0
        vecs = [
            self._unit(np.asarray(column_vectors[m], dtype=np.float32))
            for m in members
            if m in column_vectors
        ]
        if len(vecs) < 2:
            return 1.0
        sims: list[float] = []
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                sims.append(float(np.dot(vecs[i], vecs[j])))
        return float(np.mean(sims)) if sims else 1.0

    # -- HDBSCAN -------------------------------------------------------------
    def _run_hdbscan(self, matrix: np.ndarray) -> np.ndarray:
        from sklearn.cluster import HDBSCAN

        n = matrix.shape[0]
        min_cluster = min(self.min_cluster_size, max(2, n // 2))
        model = HDBSCAN(
            min_cluster_size=min_cluster,
            min_samples=self.min_samples,
            metric="euclidean",
        )
        return model.fit_predict(matrix)

    @staticmethod
    def _labels_to_groups(columns: list[str], labels: np.ndarray) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        noise_seq = 0
        for col, lab in zip(columns, labels):
            lab = int(lab)
            if lab == -1:
                key = f"noise_{noise_seq}"
                noise_seq += 1
            else:
                key = f"h{lab}"
            groups.setdefault(key, []).append(col)
        return groups

    # -- STEP 10 + 11: label + validate -------------------------------------
    def _label_and_validate(
        self,
        groups: dict[str, list[str]],
        mappings: dict[str, ColumnMapping],
        column_vectors: dict[str, np.ndarray],
    ) -> list[Cluster]:
        clusters: list[Cluster] = []
        queue = list(groups.values())

        while queue:
            members = queue.pop(0)
            if not members:
                continue
            dist, dominant, purity = self._purity(members, mappings)

            # STEP 11: split impure multi-domain clusters by domain.
            if purity < self.purity_threshold and len(members) > 1 and len(dist) > 1:
                by_domain: dict[str, list[str]] = {}
                for m in members:
                    by_domain.setdefault(mappings[m].domain, []).append(m)
                # Only split if it actually separates (>1 resulting group).
                if len(by_domain) > 1:
                    queue.extend(by_domain.values())
                    continue

            clusters.append(
                self._make_cluster(
                    len(clusters),
                    members,
                    dist,
                    dominant,
                    purity,
                    mappings,
                    column_vectors,
                )
            )

        # Stable ids by size desc then name.
        clusters.sort(key=lambda c: (-len(c.columns), c.dominant_domain))
        for i, cl in enumerate(clusters):
            cl.cluster_id = f"cluster_{i}"
        return clusters

    def _make_cluster(
        self,
        seq: int,
        members: list[str],
        dist: dict[str, float],
        dominant: str,
        purity: float,
        mappings: dict[str, ColumnMapping],
        column_vectors: dict[str, np.ndarray],
    ) -> Cluster:
        avg_conf = float(np.mean([mappings[m].confidence for m in members])) if members else 0.0
        coherence = self._embedding_coherence(members, column_vectors)
        cluster_conf = round(0.4 * purity + 0.35 * avg_conf + 0.25 * coherence, 4)
        return Cluster(
            cluster_id=f"cluster_{seq}",
            cluster_name=self._cluster_name(dominant),
            cluster_confidence=cluster_conf,
            columns=sorted(members),
            dominant_domain=dominant,
            purity=purity,
            domain_distribution=dist,
            embedding_coherence=coherence,
            avg_domain_confidence=avg_conf,
            explainability={
                "dominant_domain_share": round(purity, 4),
                "avg_domain_confidence": round(avg_conf, 4),
                "embedding_coherence": round(coherence, 4),
                "member_count": len(members),
                "domain_votes": dist,
            },
        )

    @staticmethod
    def _purity(
        members: list[str], mappings: dict[str, ColumnMapping]
    ) -> tuple[dict[str, float], str, float]:
        votes: dict[str, int] = {}
        for m in members:
            d = mappings[m].domain
            votes[d] = votes.get(d, 0) + 1
        total = sum(votes.values()) or 1
        dist = {d: c / total for d, c in votes.items()}
        dominant = max(votes, key=votes.get)
        purity = votes[dominant] / total
        return dist, dominant, purity

    @staticmethod
    def _cluster_name(domain: str) -> str:
        pretty = domain.replace("_", " ").strip().title()
        return f"{pretty} Cluster" if pretty else "Cluster"

    def _singleton(
        self,
        column: str,
        mappings: dict[str, ColumnMapping],
        column_vectors: dict[str, np.ndarray],
    ) -> Cluster:
        dom = mappings[column].domain
        conf = round(mappings[column].confidence, 4)
        return Cluster(
            cluster_id="cluster_0",
            cluster_name=self._cluster_name(dom),
            cluster_confidence=conf,
            columns=[column],
            dominant_domain=dom,
            purity=1.0,
            domain_distribution={dom: 1.0},
            embedding_coherence=1.0,
            avg_domain_confidence=conf,
            explainability={
                "dominant_domain_share": 1.0,
                "avg_domain_confidence": conf,
                "embedding_coherence": 1.0,
                "member_count": 1,
                "domain_votes": {dom: 1.0},
            },
        )
