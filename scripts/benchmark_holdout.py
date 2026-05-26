import csv
import json
import time
import sys
import argparse
from pathlib import Path
from json import JSONDecodeError

# Ensure repo root is on PYTHONPATH so top-level imports like `core` resolve
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

# Import your ingestion and pipeline functions
from core.ingestion import dataframe_for_uploaded_dataset
from pipelines.semantic_runner import run_semantic_pipeline


def _resolve_expected_ground_truth(csv_path: str) -> dict[str, str]:
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


def run_holdout_benchmark(dataset: str | None = None, dataset_domain: str | None = None):
    print("=" * 70)
    print("📊 HOLDOUT DATASET BENCHMARK (mock_mospi.csv)")
    print("=" * 70)

    # 2. Point to the physical alternate dataset
    if dataset:
        p = Path(dataset)
        file_path = p if p.is_absolute() else (repo_root / p)
    else:
        file_path = repo_root / "test_data" / "Economics - MoSPI.csv"
    
    if not file_path.exists():
        print(f"❌ Error: Could not find dataset at {file_path}")
        return

    # Extract column names directly from the CSV header
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        columns = next(reader)

    print(f"🚀 Processing {len(columns)} columns from {file_path.name}...")

    expected_gt = _resolve_expected_ground_truth(str(file_path))
    if not expected_gt:
        print(f"❌ No ground-truth mapping found in ground_truth.json for {file_path.name}.")
        return
    
    # 3. Run the Pipeline
    t0 = time.perf_counter()
    out = run_semantic_pipeline(columns, dataset_domain=dataset_domain)
    execution_time = time.perf_counter() - t0

    # 4. Grade the Output
    mapping = out.get("semantic_mapping") or {}
    correct = 0
    failed = []

    for col, expected in expected_gt.items():
        if col not in columns:
            continue # Skip if our ground truth expects a column not in this specific file
            
        pred = (mapping.get(col) or {}).get("domain") or "UNKNOWN"
        
        # Exact match or Dynamic relaxed match
        is_match = (pred == expected) or (pred.startswith(f"dyn_{expected}"))
        
        if is_match:
            correct += 1
        else:
            failed.append(f"{col} (Expected: {expected}, Got: {pred})")

    # Only grade based on the intersection of columns found in both the file and the answer key
    testable_columns = len([c for c in columns if c in expected_gt])
    accuracy = (correct / testable_columns) * 100 if testable_columns > 0 else 0

    print("\n🎯 HOLDOUT BENCHMARK RESULTS:")
    print(f"  ⏱️ Execution Time:  {execution_time:.2f} seconds")
    print(f"  📈 System Accuracy: {accuracy:.1f}% ({correct}/{testable_columns} correct)")

    if failed:
        print("\n❌ MISCLASSIFICATIONS:")
        for f in failed:
            print(f"  - {f}")
    else:
        print("\n🌟 FLAWLESS RUN! The engine generalizes perfectly to unseen datasets.")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Semantic Holdout Benchmark.")
    parser.add_argument("--dataset", type=str, required=True, help="Path to the test CSV file.")
    
    # --- ADD THIS NEW ARGUMENT ---
    parser.add_argument("--domain", type=str, default=None, help="Context of the dataset (e.g., 'Economics Dataset')")
    
    args = parser.parse_args()
    
    # Pass both arguments to your main function (default domain: 'Economics')
    domain = args.domain or "Economics"
    run_holdout_benchmark(args.dataset, domain)