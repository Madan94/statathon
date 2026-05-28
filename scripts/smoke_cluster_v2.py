"""Smoke test for Batch 5 cluster quality + stability + semantic naming."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from model.semantic_mapping.cluster_engine import ClusterEngine
from model.semantic_mapping.cluster_quality import (
    evaluate_clusters, stability_score, semantic_cluster_name,
)

np.random.seed(7)

# Build synthetic embeddings: 3 clear clusters of 5 columns each
dim = 16
def cluster_center(seed):
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1, dim)

centers = [cluster_center(s) for s in [1, 2, 3]]
columns = []
embeddings = {}
for ci, c in enumerate(centers):
    for j in range(5):
        col = f"c{ci}_var{j}"
        columns.append(col)
        embeddings[col] = c + np.random.normal(0, 0.15, dim)

# Cluster
engine = ClusterEngine()
clusters = engine.cluster_columns(embeddings)
print(f"Found {len(clusters)} clusters")
for k, m in clusters.items():
    print(f"  {k}: {m}")

# Quality
quality = evaluate_clusters(clusters, embeddings)
print(f"\nQuality:")
print(f"  silhouette       = {quality['silhouette']}")
print(f"  davies_bouldin   = {quality['davies_bouldin']}")
print(f"  calinski_harab.  = {quality['calinski_harabasz']}")
print(f"  verdict          = {quality['verdict']}")
print(f"  per-cluster cohesions:")
for k, info in quality["per_cluster"].items():
    print(f"    {k}: cohesion={info['cohesion']} size={info['size']}")

# Stability
stab = stability_score(embeddings, engine.cluster_columns, n_resamples=8, frac=0.8)
ari = stab['stability_ari']
ari_str = f"{ari:.3f}" if isinstance(ari, (int, float)) else "n/a"
print(f"\nStability: ARI={ari_str} verdict={stab['verdict']} samples={stab['samples']}")

# Semantic naming
print("\nSemantic naming:")
test_members = ["age_male", "age_female", "age_youth", "age_senior"]
print(f"  {test_members} -> {semantic_cluster_name(test_members, None)}")
domain_map = {
    "age_male": "demographic", "age_female": "demographic",
    "age_youth": "demographic", "age_senior": "demographic",
}
print(f"  (with domain map) -> {semantic_cluster_name(test_members, domain_map)}")
test_members2 = ["wheat_yield", "rice_yield", "maize_yield"]
domain_map2 = {"wheat_yield": "agriculture", "rice_yield": "agriculture", "maize_yield": "agriculture"}
print(f"  agriculture cluster -> {semantic_cluster_name(test_members2, domain_map2)}")
