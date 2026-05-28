"""Clustering accuracy benchmark with domain-aware reclustering."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from model.semantic_mapping.cluster_engine_v2 import cluster_columns_v2

rng = np.random.default_rng(11)
dim = 32

# Build 4 ground-truth clusters with overlap noise
def make_cluster(center_seed, n=6):
    center = rng.normal(0, 1, dim)
    return [center + rng.normal(0, 0.20, dim) for _ in range(n)]

embeddings = {}
domain_labels = {}
ground_truth_clusters = [
    ("labor",        ["employment_rate", "unemployment_rate", "lfpr", "wpr", "labor_force", "hours_worked"]),
    ("agri",         ["wheat_yield", "rice_yield", "maize_yield", "soybean_yield", "cropped_area", "sown_area"]),
    ("demographic",  ["age", "gender", "household_size", "marital_status", "religion", "dob"]),
    ("financial",    ["income", "expenditure", "savings", "tax_paid", "loan_amount", "interest_paid"]),
]
for cluster_idx, (label, cols) in enumerate(ground_truth_clusters):
    vecs = make_cluster(cluster_idx)
    for col, vec in zip(cols, vecs):
        embeddings[col] = vec
        domain_labels[col] = label

print(f"Dataset: {len(embeddings)} columns across {len(ground_truth_clusters)} ground-truth clusters")

# Run v2 with domain awareness
result = cluster_columns_v2(embeddings, column_domains=domain_labels, target_silhouette=0.55)

print(f"\nWinner: method={result['method']} params={result['params']}")
print(f"Silhouette: {result['quality'].get('silhouette'):.3f}  Davies-Bouldin: {result['quality'].get('davies_bouldin'):.3f}")
da = result['domain_alignment'] or {}
print(f"Domain alignment: V={da.get('v_measure')} homogeneity={da.get('homogeneity')} ARI={da.get('adjusted_rand_index')} verdict={da.get('verdict')}")

print(f"\n{len(result['clusters'])} clusters found (target=4):")
for name, members in result['clusters'].items():
    # which ground-truth domain is dominant?
    domains_in_cluster = [domain_labels[m] for m in members if m in domain_labels]
    if domains_in_cluster:
        from collections import Counter
        most_common, count = Counter(domains_in_cluster).most_common(1)[0]
        purity = count / len(members)
        print(f"  [{name:>30}] {len(members):>2d} cols, dominant={most_common} purity={purity:.2f}")
        if purity < 1.0:
            wrong = [m for m in members if domain_labels.get(m) != most_common]
            print(f"     mixed-in: {wrong}")

print(f"\nCandidate runs explored:")
for c in result['candidates']:
    sil = c.get('silhouette')
    sil_s = f"{sil:.3f}" if isinstance(sil, (int, float)) else "—"
    va = c.get('domain_alignment_v_measure')
    va_s = f"{va:.3f}" if isinstance(va, (int, float)) else "—"
    print(f"  {c['method']:>12s} {str(c['params']):<55s} sil={sil_s} V={va_s} clusters={c['cluster_count']}")
