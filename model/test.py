import json
import numpy as np
from semantic_mapping.semantic_pipeline import SemanticPipeline


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


pipeline = SemanticPipeline()

columns = [
    "person_id",
    "age_years",
    "gender_code",
    "marital_status",

    "education_level",
    "education_years",

    "occupation_type",
    "employment_status",

    "salary_monthly",
    "annual_income",
    "household_income",

    "district_name",
    "district_code",
    "state_name",
    "country",

    "household_size",
    "number_of_children",

    "population_density",
    "urban_rural_flag",

    "survey_year",
    "survey_month",

    "health_insurance",
    "medical_expense",

    "internet_access",
    "mobile_phone"
]

result = pipeline.run(columns)


# --- Pretty Print ---
print("=" * 70)
print("DATASET CONTEXT")
print("=" * 70)
ctx = result["dataset_context"]
print(f"  Inferred type: {ctx['inferred_type']}")
for k, v in ctx["context_scores"].items():
    print(f"    {k:20s} : {v:.4f}")

print("\n" + "=" * 70)
print("SEMANTIC DOMAIN MAPPING")
print("=" * 70)
for col, info in result["semantic_mapping"].items():
    print(f"  {col:25s} -> {info['domain']:20s}  (conf: {info['confidence']:.4f}  cluster: {info['cluster_support']:.2f}  graph: {info['graph_consistency']:.2f})")

print("\n" + "=" * 70)
print("COLUMN CLUSTERS")
print("=" * 70)
for cl in result["clusters"]:
    print(f"  {cl['cluster_id']:15s} | domain: {cl['domain']:15s} | support: {cl['support']:.2f} | members: {cl['columns']}")

print("\n" + "=" * 70)
print("PRIORITY DEPENDENCIES (top influencers)")
print("=" * 70)
for col, deps in result["priority_dependencies"].items():
    if deps:
        dep_str = ", ".join(f"{d['column']}({d['score']:.3f})" for d in deps[:3])
        print(f"  {col:25s} <- {dep_str}")

print("\n" + "=" * 70)
print("SCHEMA GRAPH SUMMARY")
print("=" * 70)
graph = result["schema_graph"]
print(f"  Nodes: {len(graph['nodes'])}")
print(f"  Edges: {len(graph['edges'])}")

# Save full result to JSON
with open("phase2_output.json", "w") as f:
    json.dump(result, f, indent=2, cls=NumpyEncoder)
print("\nFull output saved to phase2_output.json")