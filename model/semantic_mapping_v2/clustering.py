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

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "cluster_confidence": round(self.cluster_confidence, 4),
            "columns": self.columns,
            "dominant_domain": self.dominant_domain,
            "purity": round(self.purity, 4),
            "domain_distribution": {k: round(v, 4) for k, v in self.domain_distribution.items()},
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
    ) -> tuple[list[Cluster], dict[str, str]]:
        columns = [c for c in features if c in column_vectors]
        if not columns:
            return [], {}
        if len(columns) == 1:
            cl = self._singleton(columns[0], mappings)
            return [cl], {columns[0]: cl.cluster_id}

        matrix = self._build_feature_matrix(columns, features, mappings, column_vectors)
        labels = self._run_hdbscan(matrix)
        groups = self._labels_to_groups(columns, labels)

        clusters = self._label_and_validate(groups, mappings)
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
    ) -> np.ndarray:
        domain_list = sorted({mappings[c].domain for c in columns})
        domain_index = {d: i for i, d in enumerate(domain_list)}
        dtype_list = sorted({features[c].dtype for c in columns})
        dtype_index = {d: i for i, d in enumerate(dtype_list)}

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

            rows.append(np.concatenate([emb, dom, samp, stat, typ]))
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
        self, groups: dict[str, list[str]], mappings: dict[str, ColumnMapping]
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

            clusters.append(self._make_cluster(len(clusters), members, dist, dominant, purity, mappings))

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
    ) -> Cluster:
        avg_conf = float(np.mean([mappings[m].confidence for m in members])) if members else 0.0
        cluster_conf = round(0.6 * purity + 0.4 * avg_conf, 4)
        return Cluster(
            cluster_id=f"cluster_{seq}",
            cluster_name=self._cluster_name(dominant),
            cluster_confidence=cluster_conf,
            columns=sorted(members),
            dominant_domain=dominant,
            purity=purity,
            domain_distribution=dist,
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

    def _singleton(self, column: str, mappings: dict[str, ColumnMapping]) -> Cluster:
        dom = mappings[column].domain
        return Cluster(
            cluster_id="cluster_0",
            cluster_name=self._cluster_name(dom),
            cluster_confidence=round(mappings[column].confidence, 4),
            columns=[column],
            dominant_domain=dom,
            purity=1.0,
            domain_distribution={dom: 1.0},
        )
