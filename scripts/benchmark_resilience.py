import pandas as pd
import random
import time
import argparse
import json
from pathlib import Path
import sys
from json import JSONDecodeError

# Ensure the script can find your internal modules
repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root / "model"))

from semantic_mapping.semantic_pipeline import SemanticPipeline

def simulate_enumerator_shorthand(column_name: str) -> str:
    """Simulates realistic field-data corruption by dropping vowels and adding random typos."""
    if len(column_name) < 4:
        return column_name
        
    vowels = "aeiouAEIOU"
    # 1. Drop random vowels (common in MoSPI shorthand)
    shorthand = "".join([c for c in column_name if c not in vowels or random.random() > 0.7])
    
    # 2. Simulate systemic prefixes/suffixes (e.g., 'raw_wage_val')
    prefixes = ["raw_", "sys_", "tmp_", "v_"]
    suffixes = ["_val", "_str", "_cd", "_id"]
    
    if random.random() > 0.5:
        shorthand = random.choice(prefixes) + shorthand
    if random.random() > 0.5:
        shorthand = shorthand + random.choice(suffixes)
        
    return shorthand

dataset_domain_global: str | None = "Socio-Economic"


def _load_expected_ground_truth(csv_path: str) -> dict[str, str]:
    gt_file = repo_root / "test_data" / "ground_truth.json"
    if not gt_file.exists():
        return {}

    try:
        with open(gt_file, "r", encoding="utf-8") as f:
            all_gts = json.load(f)
    except (OSError, JSONDecodeError) as exc:
        print(f"❌ Failed to read ground_truth.json: {exc}")
        return {}

    dataset_name = Path(csv_path).name
    normalized = {str(key).strip().lower(): value for key, value in all_gts.items() if isinstance(value, dict)}
    for candidate in (dataset_name, Path(csv_path).stem, str(csv_path)):
        resolved = normalized.get(str(candidate).strip().lower())
        if resolved:
            return resolved

    if len(normalized) == 1:
        return next(iter(normalized.values()))

    return {}


def run_resilience_test(csv_path: str):
    print(f"\n📊 INITIALIZING SEMANTIC RESILIENCE TEST")
    print(f"📁 Dataset: {csv_path}")
    
    try:
        df = pd.read_csv(csv_path, nrows=0) # Only need headers
        clean_columns = list(df.columns)
    except Exception as e:
        print(f"❌ Failed to load CSV: {e}")
        return

    expected_gt = _load_expected_ground_truth(csv_path)
    if not expected_gt:
        print("❌ No ground-truth mapping found in test_data/ground_truth.json for this dataset.")
        return

    pipeline = SemanticPipeline()
    
    # ==========================================
    # PASS 1: The Clean Baseline
    # ==========================================
    print("\n🚀 PASS 1: Running Baseline (Clean Headers)...")
    start_time = time.time()
    baseline_result = pipeline.run(clean_columns, dataset_domain=dataset_domain_global)
    baseline_time = time.time() - start_time
    
    baseline_mapping = {
        col: data["domain"] 
        for col, data in baseline_result.get("semantic_mapping", {}).items()
    }
    
    # ==========================================
    # PASS 2: The Dynamic Corruption
    # ==========================================
    noisy_columns = [simulate_enumerator_shorthand(c) for c in clean_columns]
    noise_map = dict(zip(noisy_columns, clean_columns))
    
    print("\n🧬 Generating Dynamically Corrupted Schema:")
    for clean, noisy in noise_map.items():
        print(f"   • {clean}  ➔  {noisy}")

    print("\n🚀 PASS 2: Running Resilience Test (Corrupted Headers)...")
    start_time = time.time()
    noisy_result = pipeline.run(noisy_columns, dataset_domain=dataset_domain_global)
    noisy_time = time.time() - start_time
    
    noisy_mapping = {
        col: data["domain"] 
        for col, data in noisy_result.get("semantic_mapping", {}).items()
    }
    
    # ==========================================
    # EVALUATION
    # ==========================================
    print("\n======================================================================")
    print("🎯 SEMANTIC RESILIENCE RESULTS")
    print("======================================================================")
    
    preserved_count = 0
    correct_baseline = 0
    correct_drift = 0
    failures = []
    
    for noisy_col in noisy_columns:
        clean_origin = noise_map[noisy_col]
        baseline_domain = baseline_mapping.get(clean_origin)
        drift_domain = noisy_mapping.get(noisy_col)
        expected_domain = expected_gt.get(clean_origin)

        if baseline_domain == expected_domain:
            correct_baseline += 1
        if drift_domain == expected_domain:
            correct_drift += 1
        
        if baseline_domain == drift_domain and drift_domain == expected_domain:
            preserved_count += 1
        else:
            failures.append({
                "clean": clean_origin,
                "noisy": noisy_col,
                "expected_domain": expected_domain,
                "baseline_domain": baseline_domain,
                "drift_domain": drift_domain
            })

    total_cols = len(clean_columns)
    resilience_score = (correct_drift / total_cols) * 100

    print(f"⏱️ Baseline Time: {baseline_time:.2f}s | Drift Time: {noisy_time:.2f}s")
    print(f"🛡️ Baseline Accuracy: {(correct_baseline / total_cols) * 100:.1f}% ({correct_baseline}/{total_cols})")
    print(f"🛡️ Drift Accuracy: {resilience_score:.1f}% ({correct_drift}/{total_cols})")
    print(f"🛡️ Stable Correct Mappings: {(preserved_count / total_cols) * 100:.1f}% ({preserved_count}/{total_cols})")
    
    if failures:
        print("\n❌ SEMANTIC FRACTURES (Where noise broke the pipeline):")
        for fail in failures:
            print(f"  - '{fail['noisy']}' (from '{fail['clean']}')")
            print(f"    Expected: {fail['expected_domain']} | Baseline: {fail['baseline_domain']} | Drift: {fail['drift_domain']}")
    else:
        print("\n✅ PERFECT RESILIENCE: The Bi-Encoder and Graph successfully routed 100% of the corrupted data.")
    print("======================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test engine resilience against dynamic data drift.")
    parser.add_argument("--dataset", type=str, required=True, help="Path to the test CSV file.")
    parser.add_argument("--domain", type=str, default=None, help="Optional dataset context (e.g., 'Economics Data')")
    args = parser.parse_args()
    
    # set the global domain to pass into the pipeline without changing function signature
    if getattr(args, 'domain', None):
        dataset_domain_global = args.domain
    else:
        dataset_domain_global = "Socio-Economic"
    run_resilience_test(args.dataset)