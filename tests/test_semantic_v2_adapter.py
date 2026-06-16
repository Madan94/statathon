"""Tests for V2 → legacy cluster adapter mapping."""
from __future__ import annotations

from pipelines.semantic_v2_adapter import v2_to_legacy_bundle


def test_v2_to_legacy_bundle_maps_cluster_metrics():
    bundle = v2_to_legacy_bundle(
        {
            "clusters": {
                "cluster_0": {
                    "cluster_id": "cluster_0",
                    "dominant_domain": "demographic",
                    "cluster_confidence": 0.77,
                    "purity": 0.92,
                    "embedding_coherence": 0.81,
                    "columns": ["age", "gender"],
                    "domain_distribution": {"demographic": 1.0},
                }
            },
            "usecase": {"usecase": "demography", "confidence": 0.8},
        }
    )
    assert len(bundle["clusters"]) == 1
    cl = bundle["clusters"][0]
    assert cl["domain"] == "demographic"
    assert cl["support_score"] == 0.77
    assert cl["domain_purity"] == 0.92
    assert cl["embedding_coherence"] == 0.81
