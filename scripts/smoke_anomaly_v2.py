"""Smoke test for Batch 2 anomaly upgrades."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from outliers.fit_engine import method_recommendation
from outliers.anomaly_handler import build_anomaly_intelligence

np.random.seed(42)

normal = pd.Series(np.random.normal(100, 15, 500))
r1 = method_recommendation(normal)
print(f"NORMAL : rec={r1['recommended']} z={r1['z_score_confidence']:.3f} iqr={r1['iqr_confidence']:.3f}")
print(f"  reason: {r1['rationale']}")

skew = pd.Series(np.random.lognormal(2, 1, 500))
r2 = method_recommendation(skew)
print(f"SKEW   : rec={r2['recommended']} z={r2['z_score_confidence']:.3f} iqr={r2['iqr_confidence']:.3f}")
print(f"  reason: {r2['rationale']}")

bi = pd.Series(np.concatenate([np.random.normal(50, 5, 250), np.random.normal(150, 5, 250)]))
r3 = method_recommendation(bi)
print(f"BIMODAL: rec={r3['recommended']} z={r3['z_score_confidence']:.3f} iqr={r3['iqr_confidence']:.3f}")
print(f"  reason: {r3['rationale']}")

uniform = pd.Series(np.random.uniform(0, 100, 200))
r4 = method_recommendation(uniform)
print(f"UNIFORM: rec={r4['recommended']} z={r4['z_score_confidence']:.3f} iqr={r4['iqr_confidence']:.3f}")
print(f"  reason: {r4['rationale']}")

# heavy-tailed with outliers
heavy = np.random.normal(50, 5, 500)
heavy[::100] = np.random.normal(200, 50, 5)
heavyS = pd.Series(heavy)
r5 = method_recommendation(heavyS)
print(f"HEAVY  : rec={r5['recommended']} z={r5['z_score_confidence']:.3f} iqr={r5['iqr_confidence']:.3f}")
print(f"  reason: {r5['rationale']}")

df = pd.DataFrame({'age': normal, 'salary': skew, 'group': bi, 'flow': uniform, 'noise': heavyS, 'name': ['x']*500})
schema = {'age': 'numeric', 'salary': 'numeric', 'group': 'numeric', 'flow': 'numeric', 'noise': 'numeric', 'name': 'string'}
intel = build_anomaly_intelligence(df, schema)
print(f"\nE2E: scanned {intel['summary']['numeric_columns_scanned']} cols, found {intel['summary']['candidate_flags']} candidates")
print(f"  method breakdown: {intel['summary']['method_breakdown']}")
if intel['anomaly_candidates']:
    c = intel['anomaly_candidates'][0]
    print(f"  first candidate: col={c['column']} method={c['method']} sev={c['severity']} conf={c['confidence']:.3f}")
    print(f"  explain keys: {list(c['explain'].keys())}")
