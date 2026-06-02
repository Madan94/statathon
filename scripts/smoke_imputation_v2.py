"""Smoke test for Batch 3 imputation upgrades."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from imputation.imputation_manager import run_imputation_intelligence
from imputation.missing_mechanism import detect_missing_mechanism

np.random.seed(42)
n = 400

# MCAR scenario: missing values uniformly at random
mcar_age = pd.Series(np.random.normal(40, 10, n))
mcar_age[np.random.choice(n, 60, replace=False)] = np.nan

# MAR scenario: missing income depends on region
region = pd.Series(np.random.choice(['A', 'B', 'C'], n))
income = pd.Series(np.random.lognormal(2, 1, n))
income[(region == 'B') & (np.random.random(n) < 0.4)] = np.nan

# Categorical with missing
edu = pd.Series(np.random.choice(['HS', 'BS', 'MS', 'PhD'], n))
edu[np.random.choice(n, 30, replace=False)] = np.nan

# Helper numeric column correlated with income (donor)
salary_hint = income * 5 + np.random.normal(0, 2, n)

df = pd.DataFrame({
    'age': mcar_age,
    'region': region,
    'income': income,
    'salary_hint': salary_hint,
    'education': edu,
})
schema = {'age': 'numeric', 'region': 'string', 'income': 'numeric',
          'salary_hint': 'numeric', 'education': 'string'}

# Test the mechanism detector directly
print("=== Mechanism detection ===")
for col in ['age', 'income', 'education']:
    m = detect_missing_mechanism(df, col, schema=schema)
    print(f"  {col}: mech={m.mechanism} conf={m.confidence:.2f} top_predictors={[p['column'] for p in m.predictors[:2]]}")

# Test the full intelligence pipeline
print("\n=== Imputation intelligence ===")
result = run_imputation_intelligence(
    df, schema,
    semantic_columns={
        'age': {'confidence': 0.85},
        'income': {'confidence': 0.90},
        'education': {'confidence': 0.80},
    },
    dependency_graph={},
    schema_graph={},
    anomaly_column_blocks=None,
)
print(f"  {result['summary']}")
for r in result['imputation_results']:
    print(f"\n  {r['column']} ({r['missing_count']} missing, mech={r['mechanism']['mechanism']}, donor_quality={r['donor_quality']:.2f}):")
    print(f"    recommended: {r['recommended']} (band={r['confidence_band']}, score={r['confidence']:.3f})")
    for rm in r['ranked_methods']:
        print(f"      - {rm['method']:6s} {rm['score']:.3f}  {rm['reason']}")
