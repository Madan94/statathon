"""Imputation accuracy benchmark with cross-validation."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from imputation.executors import (
    evaluate_methods, impute_mean, impute_median, impute_quantile_match,
    impute_knn, impute_group_conditional,
)

rng = np.random.default_rng(2026)
n = 500

# Three column flavours with different optimal imputers
# 1) Normal column (mean should win)
age = rng.normal(40, 10, n)

# 2) Right-skewed (median should beat mean)
income = rng.lognormal(7, 1, n)

# 3) MAR scenario — strong predictor, KNN should win
education_years = rng.uniform(0, 18, n)
salary = education_years * 2000 + rng.normal(0, 1500, n)  # strongly correlated

df = pd.DataFrame({"age": age, "income": income, "education_years": education_years, "salary": salary})

# Hide some values randomly across each column
for col in df.columns:
    df.loc[rng.choice(n, 50, replace=False), col] = np.nan

results = {}
for col in ["age", "income", "salary"]:
    series = df[col]
    eval_result = evaluate_methods(series, df)
    print(f"\n=== {col} ===")
    for r in eval_result["method_scores"]:
        marker = "<-- WINNER" if r["method"] == eval_result["winner"] else ""
        print(f"  {r['method']:>14s} rmse={r['rmse']:>9.2f} mae={r['mae']:>9.2f}  {marker}")
    results[col] = eval_result

# Verdict per column
print("\n=== Verdict ===")
expectations = {
    "age": ("mean", "near-normal: mean optimal"),
    "income": ("median", "right-skewed: median or quantile-match optimal"),
    "salary": ("knn", "MAR: KNN should win"),
}
passes = 0
total = len(expectations)
for col, (expected, reason) in expectations.items():
    winner = results[col]["winner"]
    # For skewed, accept median OR quantile_match
    ok = (winner == expected
          or (expected == "median" and winner in ("median", "quantile_match"))
          or (expected == "knn" and winner == "knn"))
    print(f"  {col:>12s}: expected={expected:<14s} winner={winner:<14s} {'PASS' if ok else 'FAIL'}  ({reason})")
    passes += int(ok)
print(f"\nMethod selection accuracy: {passes}/{total}")

# Distribution preservation test
print("\n=== Distribution preservation (income column) ===")
full_income = df["income"].dropna()
mean_imp = impute_mean(df["income"])
qm_imp = impute_quantile_match(df["income"])
print(f"  observed   : mean={full_income.mean():.1f}  std={full_income.std():.1f}  skew={full_income.skew():.2f}")
print(f"  mean impute: mean={mean_imp.mean():.1f}  std={mean_imp.std():.1f}  skew={mean_imp.skew():.2f}")
print(f"  quant match: mean={qm_imp.mean():.1f}  std={qm_imp.std():.1f}  skew={qm_imp.skew():.2f}")
