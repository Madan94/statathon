"""
V2 accuracy & generalization test.

Run from repo root:
  .\\data\\Scripts\\python.exe .\\tests\\test_semantic_mapping_v2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODEL_ROOT = _REPO_ROOT / "model"
for _path in (str(_REPO_ROOT), str(_MODEL_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from semantic_mapping_v2.pipeline import SemanticPipelineV2

def test_v2_accuracy():
    print("🧪 Running V2 Accuracy & Generalization Test...")
    pipeline = SemanticPipelineV2()
    
    # Dataset representing mixed concepts
    dataset_id = "test_survey_001"
    raw_columns = [
        "orbital_satellite_count", "rocket_launch_payload_kg",  # Should map to same 'Space' domain
        "employee_monthly_wage", "worker_salary_amount",         # Should map to same 'Labor' domain
        "patient_blood_type",                                    # Should map to 'Health'
        "random_noise_xyz"                                       # Should be uncorrelated
    ]
    
    metadata = {
        "dataset_archetype": "multi_domain_survey",
        "datatypes": {col: "string" for col in raw_columns},
        "column_metadata": {col: {"description": "test data"} for col in raw_columns}
    }

    # Execute
    results = pipeline.run(dataset_id, raw_columns, metadata)
    mapping = results["semantic_mapping"]

    # 1. VERIFY GENERALIZATION (Grouping)
    space_doms = {mapping["orbital_satellite_count"]["domain"], mapping["rocket_launch_payload_kg"]["domain"]}
    labor_doms = {mapping["employee_monthly_wage"]["domain"], mapping["worker_salary_amount"]["domain"]}
    
    print("\n--- GENERALIZATION CHECK ---")
    print(f"Space group domains: {space_doms}")
    print(f"Labor group domains: {labor_doms}")
    
    # 2. VERIFY NOISE HANDLING
    noise_dom = mapping["random_noise_xyz"]["domain"]
    noise_conf = mapping["random_noise_xyz"]["confidence"]
    print(f"Noise mapping: {noise_dom} (Conf: {noise_conf})")

    # Assertions
    assert len(space_doms) == 1, "❌ FAILED: Space columns did not generalize to one domain."
    assert len(labor_doms) == 1, "❌ FAILED: Labor columns did not generalize to one domain."
    assert noise_dom == "uncorrelated", "❌ FAILED: Noise was incorrectly mapped to a domain."
    
    print("\n✅ All accuracy checks passed!")

if __name__ == "__main__":
    test_v2_accuracy()
