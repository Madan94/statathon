"""Smoke test for Batch 4 domain mapping upgrades."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from analytics import profile_column
from model.semantic_mapping.similarity_engine import SimilarityEngine
from model.semantic_mapping.confidence_engine import ConfidenceEngine
from model.semantic_mapping.dynamic_domain_synth import synthesise_dynamic_domains
from model.semantic_mapping.domain_synthesizer import unify_domains

np.random.seed(0)

# Test multi-signal similarity
print("=== Multi-signal similarity ===")
profile = profile_column(pd.Series(np.random.uniform(0, 100, 200)), column_name="employment_rate")
score = SimilarityEngine.compose_signals(
    cosine=0.78,
    column_name="employment_rate",
    domain_name="labor_market",
    domain_aliases=["employment", "workforce"],
    domain_keywords=["rate", "employment", "labor"],
    domain_metadata={"expected_dtype": "numeric", "expected_kind": "percentage", "expected_range": [0, 100]},
    column_dtype="float64",
    column_profile=profile,
    cluster_support=0.7,
    graph_consistency=0.5,
)
print(f"  employment_rate -> labor_market: confidence={score['value']:.3f} band={score['band']}")
print("  contributions:")
for sig, info in score['explain'].items():
    print(f"    {sig:20s} v={info['value']:.2f} w={info['weight']:.2f} contrib={info['contribution_pct']:.1f}%")

# Compare to a poorly-fitting domain
score_bad = SimilarityEngine.compose_signals(
    cosine=0.30,
    column_name="employment_rate",
    domain_name="agricultural_production",
    domain_aliases=["crops", "harvest"],
    domain_keywords=["yield", "crop"],
    domain_metadata={"expected_dtype": "numeric", "expected_kind": "monetary"},
    column_dtype="float64",
    column_profile=profile,
)
print(f"\n  employment_rate -> agricultural_production: confidence={score_bad['value']:.3f} band={score_bad['band']}")

# Dynamic domain synthesis
print("\n=== Dynamic domain synthesis ===")
columns = [
    "employment_rate_male", "employment_rate_female", "employment_rate_youth",
    "wheat_yield_per_acre", "rice_yield_per_acre", "maize_yield_per_acre",
    "household_income", "household_expenditure", "household_savings",
    "random_misc_column"
]
static_best = {
    "employment_rate_male": ("labor_market", 0.85),
    "employment_rate_female": ("labor_market", 0.85),
    "wheat_yield_per_acre": ("agriculture", 0.40),  # weak — should be candidate
    "rice_yield_per_acre": ("agriculture", 0.42),   # weak
    "maize_yield_per_acre": ("agriculture", 0.38),  # weak
    "household_income": ("income", 0.91),
    "household_expenditure": ("expenditure", 0.88),
    "household_savings": ("savings", 0.81),
    "random_misc_column": ("uncorrelated", 0.20),
    "employment_rate_youth": ("labor_market", 0.80),
}
dynamic = synthesise_dynamic_domains(
    columns=columns,
    column_profiles=None,
    similarity_matrix=None,
    static_best_per_column=static_best,
)
print(f"  {len(dynamic)} dynamic domains synthesised:")
for d in dynamic:
    print(f"    - {d.name} ({d.display_name}): members={d.member_columns}")

# Unification
print("\n=== Domain unification ===")
static_dict = {
    "demographic": {
        "labor_market": {"name": "labor_market", "keywords": ["employment", "labor", "workforce"]},
        "income": {"name": "income", "keywords": ["income", "salary", "wage"]},
    },
    "agriculture": {
        "yield": {"name": "agriculture_yield", "keywords": ["yield", "production"]},
    },
}
unified = unify_domains(static_dict, dynamic)
print(f"  Total unified domains: {len(unified)}")
for u in unified[:6]:
    print(f"    - {u.name} (source={u.source}, parent={u.parent})")
