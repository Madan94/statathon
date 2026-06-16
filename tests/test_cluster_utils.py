"""Tests for cluster payload normalization (V2 → legacy UI shape)."""
from __future__ import annotations

from analysis_state.cluster_utils import cluster_from_db_row, unify_cluster_record


def test_unify_v2_cluster_record():
    cl = unify_cluster_record(
        {
            "cluster_id": "cluster_0",
            "dominant_domain": "demographic",
            "cluster_confidence": 0.82,
            "purity": 0.91,
            "columns": ["age", "gender"],
            "domain_distribution": {"demographic": 2},
        }
    )
    assert cl["domain"] == "demographic"
    assert cl["support_score"] == 0.82
    assert cl["domain_purity"] == 0.91
    assert cl["columns"] == ["age", "gender"]


def test_cluster_from_db_row_reads_metadata():
    cl = cluster_from_db_row(
        "cluster_1",
        None,
        None,
        {
            "dominant_domain": "geography",
            "cluster_confidence": 0.75,
            "purity": 0.88,
            "embedding_coherence": 0.66,
            "columns": ["state", "district"],
        },
    )
    assert cl["domain"] == "geography"
    assert cl["support_score"] == 0.75
    assert cl["domain_purity"] == 0.88
    assert cl["embedding_coherence"] == 0.66
