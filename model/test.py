import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

from semantic_mapping.semantic_pipeline import SemanticPipeline


def main():
    columns = [
        "person_id",
        "age_years",
        "gender_code",
        "marital_status",
        "education_level",
        "employment_status",
        "salary_monthly",
        "annual_income",
        "district_name",
        "household_size",
        "survey_year",
        "health_insurance",
        "internet_access",
    ]

    pipeline = SemanticPipeline()
    result = pipeline.run(columns)

    print("=== Dataset Context ===")
    print(json.dumps(result["dataset_context"], indent=2))

    print("\n=== Semantic Mapping ===")
    for col, info in result["semantic_mapping"].items():
        print(
            f"{col}: domain={info['domain']} confidence={info['confidence']:.4f} "
            f"normalized='{info['normalized_name']}'"
        )

    print("\n=== Cluster Summary ===")
    for cluster in result["clusters"]:
        print(
            f"{cluster['cluster_id']} domain={cluster['domain']} support={cluster['support']:.4f} "
            f"columns={cluster['columns']}"
        )

    print("\n=== Schema Graph ===")
    print(f"nodes={len(result['schema_graph']['nodes'])}, edges={len(result['schema_graph']['edges'])}")

    print("\n=== Audit Records ===")
    print(f"{len(result['audit_records'])} records logged")
    pipeline.print_audit_log(limit=5)

    with open("semantic_pipeline_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
        print("\nWrote semantic_pipeline_output.json")


if __name__ == "__main__":
    main()
