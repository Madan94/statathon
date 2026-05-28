"""Hard accuracy test: 10 real-world MoSPI-style columns scored against full shortlist."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from analytics import profile_column
from model.semantic_mapping.similarity_engine import SimilarityEngine
from model.semantic_mapping.dataset_domain_filter import (
    infer_dataset_archetypes, shortlist_static_domains,
)
from model.semantic_mapping.domain_synthesizer import _flatten_static

np.random.seed(42)

# Test columns with ground-truth domain assignments
test_cases = [
    # (column_name, profile_data, expected_domain, simulated_cosine_to_correct)
    ("employment_rate", np.random.uniform(0, 100, 200), "labor_market", 0.78),
    ("unemployment_rate", np.random.uniform(0, 30, 200), "labor_market", 0.74),
    ("monthly_household_income", np.random.lognormal(8, 1, 200), "income", 0.82),
    ("monthly_expenditure", np.random.lognormal(7, 1, 200), "expenditure", 0.80),
    ("age", np.random.normal(40, 15, 200), "age_group", 0.85),
    ("wheat_yield_per_acre", np.random.normal(30, 8, 200), "agriculture_yield", 0.79),
    ("rainfall_mm", np.random.gamma(2, 50, 200), "rainfall", 0.81),
    ("literacy_rate", np.random.uniform(40, 95, 200), "literacy", 0.77),
    ("state_name", pd.Series(["KA","MH","TN"]*67), "state", 0.86),
    ("dob", pd.date_range("1950-01-01", periods=200), "year", 0.40),  # ambiguous; date field
]

# Full ontology (compact)
static = {
    "labour": {
        "labor_market": {"name": "labor_market", "aliases": ["employment", "workforce"], "keywords": ["rate", "employment", "labor", "unemployment"], "expected_dtype": "numeric", "expected_kind": "percentage", "expected_range": [0, 100]},
        "wage": {"name": "wage", "aliases": ["salary"], "keywords": ["wage", "salary"], "expected_dtype": "numeric"},
    },
    "demographic": {
        "age_group": {"name": "age_group", "aliases": ["age"], "keywords": ["age"], "expected_dtype": "numeric", "expected_range": [0, 120]},
        "gender": {"name": "gender", "keywords": ["gender", "sex"], "expected_dtype": "categorical"},
        "household": {"name": "household", "keywords": ["household", "hh"], "expected_dtype": "numeric"},
    },
    "economic": {
        "income": {"name": "income", "aliases": ["earnings", "salary"], "keywords": ["income", "earnings"], "expected_dtype": "numeric"},
        "expenditure": {"name": "expenditure", "aliases": ["expense", "spending"], "keywords": ["expenditure", "expense"], "expected_dtype": "numeric"},
        "gdp": {"name": "gdp", "keywords": ["gdp"], "expected_dtype": "numeric"},
    },
    "agriculture": {
        "yield": {"name": "agriculture_yield", "aliases": ["crop_yield", "yield"], "keywords": ["yield"], "expected_dtype": "numeric"},
        "soil": {"name": "soil", "keywords": ["ph", "fertilizer"], "expected_dtype": "numeric"},
        "rainfall": {"name": "rainfall", "keywords": ["rainfall", "precipitation"], "expected_dtype": "numeric"},
        "crop": {"name": "crop", "keywords": ["wheat", "rice", "crop"], "expected_dtype": "categorical"},
    },
    "education": {
        "literacy": {"name": "literacy", "aliases": ["literacy_rate"], "keywords": ["literacy", "literate"], "expected_dtype": "numeric", "expected_range": [0, 100]},
    },
    "industrial": {
        "production": {"name": "industrial_production", "keywords": ["iip", "production"], "expected_dtype": "numeric"},
    },
    "geography": {
        "state": {"name": "state", "aliases": ["state_name"], "keywords": ["state"], "expected_dtype": "categorical"},
        "district": {"name": "district", "keywords": ["district"], "expected_dtype": "categorical"},
    },
    "time": {
        "year": {"name": "year", "keywords": ["year", "dob", "date"], "expected_dtype": "numeric"},
        "month": {"name": "month", "keywords": ["month"], "expected_dtype": "numeric"},
    },
}

flat = _flatten_static(static)
all_cols = [c[0] for c in test_cases]

# Per-dataset archetype filter
arch = infer_dataset_archetypes(all_cols)
shortlisted = shortlist_static_domains(flat, arch, columns=all_cols)
print(f"Archetypes: {[(a.archetype, round(a.score,2)) for a in arch]}")
print(f"Shortlist size: {len(shortlisted)} / {len(flat)}")

# Score each test column against shortlist
passes = 0
fails = []
print(f"\n{'col':<32s} {'expected':<22s} {'predicted':<22s} {'score':<7s} {'band':<7s}")
print("-" * 92)
for col, vals, expected, cosine_correct in test_cases:
    try:
        prof = profile_column(pd.Series(vals), column_name=col)
    except Exception:
        prof = None
    best = (None, -1, "")
    for d in shortlisted:
        cosine = cosine_correct if d["name"] == expected else max(0.15, cosine_correct * 0.5 - 0.1)
        score = SimilarityEngine.compose_signals(
            cosine=cosine,
            column_name=col,
            domain_name=d["name"],
            domain_aliases=d.get("aliases", []),
            domain_keywords=d.get("keywords", []),
            domain_metadata={k: d.get(k) for k in ("expected_dtype", "expected_kind", "expected_range")},
            column_dtype=str(prof.dtype) if prof else None,
            column_profile=prof,
        )
        if score["value"] > best[1]:
            best = (d["name"], score["value"], score["band"])

    ok = best[0] == expected and best[1] >= 0.50
    status_marker = "OK" if ok else "x"
    print(f"{col:<32s} {expected:<22s} {best[0]:<22s} {best[1]:<7.3f} {best[2]:<7s} {status_marker}")
    if ok:
        passes += 1
    else:
        fails.append((col, expected, best[0], best[1]))

print(f"\nAccuracy: {passes}/{len(test_cases)} = {passes/len(test_cases)*100:.1f}%")
if fails:
    print("Failures:")
    for f in fails:
        print(f"  {f}")
