import os
import json
from dotenv import load_dotenv
from model.semantic_mapping.semantic_pipeline import SemanticPipeline

# 1. Load environment variables before pipeline initializes
load_dotenv()

def run_end_to_end_test():
    print("🚀 Initializing Semantic Pipeline...")
    pipeline = SemanticPipeline()

    # 2. The Foolproof Mathematical Crucible Dataset
    # 2. The Space Exploration Crucible Dataset (Guarantees Phase 1 Evasion)
    test_columns = [
        "employee_uid",                 # 1. Structural Bypass
        "District",                     # 2. Lexical Fast-Track
        "monthly_wage",                 # 3. Static Vector Lock
        "orbital_satellite_count",      # 4a. Dynamic Cohort Member
        "rocket_launch_payload_kg",     # 4b. Dynamic Cohort Member
        "lunar_rover_velocity",         # 4c. Dynamic Cohort Member
        "atmospheric_pressure",         # 5a. Noise / Uncorrelated
        "patient_blood_type"            # 5b. Noise / Uncorrelated
    ]

    print(f"📥 Feeding {len(test_columns)} columns into the engine...")
    
    # Run the engine with a guiding archetype (For the LLM Generator context)
    results = pipeline.run(
        columns=test_columns,
        dataset_domain="economic_survey" 
    )

    mapping = results.get("semantic_mapping", {})
    
    print("\n--- DEBUG MAPPING ---")
    print(json.dumps({k: v.get("domain") for k, v in mapping.items()}, indent=2))
    print("---------------------\n")
    
    print("\n" + "="*50)
    print("📊 ARCHITECTURAL VALIDATION RESULTS")
    print("="*50)

    # --- TEST 1: Structural Bypass ---
    emp_res = mapping.get("employee_uid", {})
    assert emp_res.get("domain") == "identifier", "❌ FAILED: Structural routing missed."
    assert emp_res.get("routing_path") == "schema_suffix_lock", "❌ FAILED: Wrong routing path for ID."
    print("✅ TEST 1 PASSED: Structural Bypass (employee_uid -> identifier)")

    # --- TEST 2: Lexical Fast-Track ---
    dist_res = mapping.get("District", {})
    assert dist_res.get("domain") == "geography", "❌ FAILED: Lexical routing missed."
    print("✅ TEST 2 PASSED: Lexical Fast-Track (District -> geography)")

    # --- TEST 3: Static Vector Sieve ---
    wage_res = mapping.get("monthly_wage", {})
    assert wage_res.get("domain") == "labor", f"❌ FAILED: Vector sieve routed to {wage_res.get('domain')}."
    assert wage_res.get("confidence") >= 0.85, "❌ FAILED: Confidence below strict threshold."
    print(f"✅ TEST 3 PASSED: Static Vector Sieve (monthly_wage -> labor, conf: {wage_res.get('confidence'):.2f})")

    # --- TEST 4: Dynamic LLM Anchoring ---
    sat_res = mapping.get("orbital_satellite_count", {})
    rocket_res = mapping.get("rocket_launch_payload_kg", {})
    rover_res = mapping.get("lunar_rover_velocity", {})
    
    dynamic_domain = sat_res.get("domain")
    assert dynamic_domain != "uncorrelated", "❌ FAILED: Space cohort dropped to uncorrelated."
    assert sat_res.get("domain") == rocket_res.get("domain") == rover_res.get("domain"), "❌ FAILED: Dynamic cohort split."
    assert sat_res.get("routing_path") == "dynamic_cluster", "❌ FAILED: Did not use dynamic routing."
    print(f"✅ TEST 4 PASSED: Dynamic LLM Anchoring (Generated Domain: '{dynamic_domain}')")
    
    # --- TEST 5: The Uncorrelated Sink ---
    atmos_res = mapping.get("atmospheric_pressure", {})
    blood_res = mapping.get("patient_blood_type", {})
    assert atmos_res.get("domain") == "uncorrelated", "❌ FAILED: Pressure forced into a domain."
    assert blood_res.get("domain") == "uncorrelated", "❌ FAILED: Blood type forced into a domain."
    print("✅ TEST 5 PASSED: Uncorrelated Sink (Noise was correctly isolated)")

    print("\n" + "="*50)
    print("🔍 VERIFYING UI REGISTRY PAYLOAD")
    print("="*50)
    
    registry = results.get("domain_registry", {})
    static_domains = registry.get("static_ontology", {}).get("macro_categories", {}).get("domains", [])
    
    assert len(static_domains) <= 15, f"❌ FAILED: Registry sent {len(static_domains)} domains to UI. Macro-trap still active."
    print(f"✅ REGISTRY PASSED: Only {len(static_domains)} Macro-Domains sent to UI.")
    
    dynamic_domains = registry.get("dynamic_domains", {})
    assert len(dynamic_domains) > 0, "❌ FAILED: Dynamic domains not added to registry."
    print(f"✅ REGISTRY PASSED: Dynamic domains registered with LLM descriptions.")

    print("\n🎉 ALL ARCHITECTURAL GATES VALIDATED SUCCESSFULLY.")

if __name__ == "__main__":
    run_end_to_end_test()