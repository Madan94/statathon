"""End-to-end smoke for the context-aware validation gate.

KG -> Rule Discovery -> Single + Multi Validation -> Classification -> User Review.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from analytics import profile_column
from pipelines.validation_gate import run_validation_gate, apply_user_decisions

rng = np.random.default_rng(2026)
n = 200

# A labour-survey-style dataset with known violations
df = pd.DataFrame({
    "age": rng.normal(40, 12, n).clip(0, 120),
    "employment_rate": rng.uniform(40, 95, n),
    "monthly_income": rng.lognormal(8, 0.7, n),
    "monthly_expenditure": rng.lognormal(7.5, 0.7, n),
    "male_pop": rng.integers(40, 60, n).astype(float),
    "female_pop": rng.integers(40, 60, n).astype(float),
    "total_pop": np.zeros(n),  # will be set so totals match
    "survey_year": rng.integers(2018, 2026, n).astype(float),
    "pincode": [f"{rng.integers(100000, 999999)}" for _ in range(n)],
})
df["total_pop"] = df["male_pop"] + df["female_pop"]

# Inject violations
df.at[5,  "age"] = 175           # CRITICAL (range)
df.at[15, "age"] = -3            # CRITICAL (range)
df.at[10, "employment_rate"] = 145  # HIGH (percentage > 100)
df.at[20, "employment_rate"] = -8   # HIGH (percentage < 0)
df.at[30, "monthly_expenditure"] = df.at[30, "monthly_income"] * 4  # multi: expenditure > income
df.at[40, "monthly_expenditure"] = df.at[40, "monthly_income"] * 3
df.at[50, "total_pop"] = df.at[50, "male_pop"] + df.at[50, "female_pop"] + 50  # aggregation fail
df.at[60, "survey_year"] = 1800  # year out of range
df.at[70, "pincode"] = "ABC123"  # invalid pincode

# Synthetic columns_meta + KG payload (what the actual pipeline would supply)
columns_meta = {
    "age": {"domain": "age_group", "confidence": 0.95},
    "employment_rate": {"domain": "labor_market", "confidence": 0.92},
    "monthly_income": {"domain": "income", "confidence": 0.90},
    "monthly_expenditure": {"domain": "expenditure", "confidence": 0.88},
    "male_pop": {"domain": "demographic", "confidence": 0.85},
    "female_pop": {"domain": "demographic", "confidence": 0.85},
    "total_pop": {"domain": "demographic", "confidence": 0.85},
    "survey_year": {"domain": "year", "confidence": 0.80},
    "pincode": {"domain": "geography", "confidence": 0.80},
}

unified_domains = [
    {"name": "age_group", "expected_range": [0, 120], "expected_dtype": "numeric"},
    {"name": "labor_market", "expected_kind": "percentage", "expected_range": [0, 100], "expected_dtype": "numeric"},
    {"name": "income", "expected_dtype": "numeric"},
    {"name": "expenditure", "expected_dtype": "numeric"},
    {"name": "demographic", "expected_dtype": "numeric"},
    {"name": "year", "expected_range": [2000, 2030], "expected_dtype": "numeric"},
]

schema_graph = {
    "edges": [
        {"source": "monthly_income", "target": "monthly_expenditure",
         "weight": 0.85, "relationship_type": "INFLUENCES"},
        {"source": "male_pop", "target": "total_pop",
         "weight": 0.95, "relationship_type": "PART_OF"},
        {"source": "female_pop", "target": "total_pop",
         "weight": 0.95, "relationship_type": "PART_OF"},
    ]
}
priority_dependencies = {
    "monthly_expenditure": [{"column": "monthly_income", "score": 0.85}],
}
archetypes = [{"archetype": "labour", "score": 0.4}, {"archetype": "economic", "score": 0.3}]

column_profiles = {c: profile_column(df[c], column_name=c).to_dict() for c in df.columns}

# Run the gate
result = run_validation_gate(
    df,
    columns_meta=columns_meta,
    schema_graph=schema_graph,
    priority_dependencies=priority_dependencies,
    column_profiles=column_profiles,
    unified_domains=unified_domains,
    archetypes=archetypes,
    analysis_id=999,
)

summary = result["summary"]
print(f"\n=== Validation Gate ===")
print(f"Rules discovered : {summary['rules_discovered']}")
print(f"Source breakdown : {summary['source_breakdown']}")
print(f"Rules fired      : {summary['rules_fired']}")
print(f"Severity         : {summary['severity_breakdown']}")
print(f"Approved (no CRITICAL)? : {summary['approved']}")

print(f"\n=== Single-column rule hits ({len(result['single_column'])}) ===")
for r in result["single_column"]:
    print(f"  [{r['severity']:8s}] {r['rule_id']:18s} {r['column']:22s} src={r['rule_source']:11s} viols={r['violation_count']:3d} conf={r['confidence']:.3f}")

print(f"\n=== Multi-column rule hits ({len(result['multi_column'])}) ===")
for r in result["multi_column"]:
    cols = ",".join(r.get("columns") or [])
    print(f"  [{r['severity']:8s}] {r['rule_id']:18s} {cols:50s} src={r['rule_source']:11s} viols={r['violation_count']:3d} conf={r['confidence']:.3f}")
    print(f"     {r['explanation']}")

print(f"\n=== Top 10 review candidates by severity x confidence ===")
for c in result["validation_candidates"][:10]:
    col = c.get("column") or ",".join(c.get("columns") or [])
    print(f"  [{c['severity']:8s}] row={c.get('row'):>4} {col:30s} value={c.get('value')}  conf={c['confidence']:.2f}  src={c['rule_source']}")

# Apply some user decisions
print(f"\n=== Applying user decisions ===")
decisions = [
    {"rule_id": "ont_range_1", "row_id": 5, "column": "age", "user_action": "REMOVE_ROW"},
    {"rule_id": "ont_range_1", "row_id": 15, "column": "age", "user_action": "MODIFY", "new_value": 35},
    {"rule_id": "ont_pct_1", "row_id": 10, "column": "employment_rate", "user_action": "TREAT_AS_MISSING"},
]
validated_df = apply_user_decisions(df, decisions)
print(f"Original rows: {len(df)} -> after decisions: {len(validated_df)}")
print(f"Age row 15 -> {validated_df.at[validated_df.index[14], 'age']}  (was -3, modified to 35)")
print(f"Employment_rate row 10 -> {validated_df.at[validated_df.index[9], 'employment_rate']}  (was 145, now NaN)")
