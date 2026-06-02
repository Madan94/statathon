import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))

from analysis_state.cluster_utils import normalize_domain_distribution, normalize_clusters_payload


def test_normalize_vote_counts_to_fractions():
    dist = normalize_domain_distribution(
        {"survey_metadata": 7, "demographic": 2, "geography": 2, "census": 2, "uncorrelated": 1}
    )
    assert abs(sum(dist.values()) - 1.0) < 0.001
    assert dist["survey_metadata"] == round(7 / 14, 4)


def test_single_domain_fallback():
    dist = normalize_domain_distribution(None, fallback_domain="demographic", column_count=2)
    assert dist == {"demographic": 1.0}


def test_normalize_clusters_payload():
    clusters = normalize_clusters_payload(
        [
            {
                "cluster_id": "c1",
                "domain": "demographic",
                "columns": ["AgeGroup", "SocialGroup"],
                "domain_distribution": {"demographic": 2},
            }
        ]
    )
    assert clusters[0]["domain_distribution"] == {"demographic": 1.0}
