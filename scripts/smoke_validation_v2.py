"""Smoke test for Batch 6 validation: expanded rules + multi-column templates."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import pandas as pd
from validation.multi_column.template_executor import (
    load_multi_column_rules, run_multi_column_rules,
)

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rule_lib = os.path.join(repo_root, "model", "config", "validation_rule_library.json")

# Counts in the rule library
data = json.loads(open(rule_lib, encoding="utf-8").read())
single = data.get("rules") or []
multi = data.get("multi_column_rules") or []
print(f"Rule library: {len(single)} single-column + {len(multi)} multi-column rules")

# Group by domain
by_domain = {}
for r in single:
    d = r.get("domain", "?")
    by_domain[d] = by_domain.get(d, 0) + 1
for d, n in sorted(by_domain.items()):
    print(f"  {d:14s}: {n} rules")

# Synthetic dataset for multi-column rules
df = pd.DataFrame({
    "household_income": [10000, 20000, 30000, 15000, 50000],
    "household_expenditure": [8000, 25000, 28000, 12000, 60000],  # row 1 and 4 violate income>=exp
    "male_pop": [50, 60, 40, 70, 55],
    "female_pop": [50, 60, 45, 30, 55],
    "total_pop": [100, 120, 90, 100, 110],  # row 4: 55+55=110 ok; row 2: 40+45=85 vs 90 violates 1% tol
    "exports": [100, 200, 300, 400, 500],
    "production": [500, 200, 800, 100, 1000],   # row 1: 200 vs 200 ok; row 3: 400 > 100 violates
    "dob": ["2020-01-01", "2025-01-01", "2030-01-01", "2020-01-01", "2018-01-01"],
    "survey_date": ["2025-12-01"] * 5,           # row 2: 2025 vs 2025-12 ok; row 3: 2030 > 2025 violates
})

violations = run_multi_column_rules(df, rule_lib)
print(f"\nMulti-column rule violations on synthetic data: {len(violations)} rules fired")
for v in violations:
    print(f"  [{v['severity'].upper():6s}] {v['rule_id']:32s} {v['violation_count']:>3d} rows  {v['explain']}")
