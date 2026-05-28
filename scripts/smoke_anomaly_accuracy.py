"""Anomaly accuracy benchmark: ensemble agreement + domain-bound enforcement."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from outliers.anomaly_handler import build_anomaly_intelligence
from outliers.ensemble_engine import enrich_anomaly_candidates, detect_domain_bound_outliers
from analytics import profile_column

rng = np.random.default_rng(2026)

# Build a dataset with KNOWN outliers we can grade against
n = 400
ages = rng.normal(40, 12, n).clip(0, 120)
incomes = rng.lognormal(2, 0.8, n)
employment_rate = rng.uniform(40, 95, n)

# Inject KNOWN outliers
# 1) Domain-bound violations (impossible values)
ages[5] = 175      # age > 120
ages[15] = -3      # age < 0
employment_rate[10] = 145  # >100% — impossible
employment_rate[20] = -8   # < 0% — impossible

# 2) Statistical outliers (extreme but possible)
incomes[30] = incomes.mean() * 50  # massive outlier
incomes[35] = incomes.mean() * 30
ages[50] = 115     # high but legal

ground_truth_outliers = {
    ("age", 5): "DOMAIN",      # > 120
    ("age", 15): "DOMAIN",     # < 0
    ("employment_rate", 10): "DOMAIN",
    ("employment_rate", 20): "DOMAIN",
    ("income", 30): "STAT",
    ("income", 35): "STAT",
}

df = pd.DataFrame({"age": ages, "income": incomes, "employment_rate": employment_rate})
schema = {c: "numeric" for c in df.columns}

# Run base anomaly intel
base = build_anomaly_intelligence(df, schema)
print(f"Base anomaly run: {len(base['anomaly_candidates'])} candidates")

# Profile columns
profiles = {c: profile_column(df[c], column_name=c).to_dict() for c in df.columns}

# Enrich with ensemble + domain bounds
enriched = enrich_anomaly_candidates(
    base["anomaly_candidates"], df=df, schema=schema, profiles=profiles,
)
print(f"Enriched run: {enriched['summary']}\n")

# Grade
print(f"{'cell':<30s} {'truth':<8s} {'detected':<12s} {'severity':<10s} {'conf':<8s} {'methods'}")
print("-" * 100)

found_ground_truth = {}
for c in enriched["anomaly_candidates"]:
    key = (c["column"], c["row"])
    if key in ground_truth_outliers:
        truth = ground_truth_outliers[key]
        found_ground_truth[key] = c
        m_str = ",".join(c["voting_methods"])
        print(f"{str(key):<30s} {truth:<8s} {'YES':<12s} {c['severity']:<10s} {c['confidence']:<8.3f} {m_str}")

# Print misses
print()
for key, truth in ground_truth_outliers.items():
    if key not in found_ground_truth:
        print(f"  MISS: {key} (truth={truth})")

# Stats
total = len(ground_truth_outliers)
hit = len(found_ground_truth)
correct_severity = sum(1 for k, c in found_ground_truth.items()
                        if c["severity"] == "EXTREME" and ground_truth_outliers[k] == "DOMAIN"
                        or c["severity"] in ("EXTREME", "MEDIUM") and ground_truth_outliers[k] == "STAT")
print(f"\nDetection rate: {hit}/{total} = {hit/total*100:.1f}%")
print(f"Severity correctness: {correct_severity}/{hit}")

# Confidence on domain violations should be >=0.95
dom_keys = [k for k, t in ground_truth_outliers.items() if t == "DOMAIN"]
dom_confs = [found_ground_truth[k]["confidence"] for k in dom_keys if k in found_ground_truth]
print(f"\nMean confidence on DOMAIN violations: {np.mean(dom_confs) if dom_confs else 0:.3f} (target: >= 0.95)")
