#!/usr/bin/env python3
"""
End-to-end semantic benchmark: synthetic labeled survey CSV → SemanticPipeline
(upload→analyze path optional via --http).

Ground truth is human-assigned base ontology labels.
This benchmark tracks Exact Matches, Relaxed Matches, and the new Waterfall Architecture metrics
(Gatekeeper Locks vs. Dynamic Fallbacks).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from json import JSONDecodeError


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _setup_paths() -> None:
    root = _repo_root()
    api = root / "api"
    model = root / "model"
    for p in (str(root), str(api), str(model)):
        if p not in sys.path:
            sys.path.insert(0, p)


# Synthetic official-style survey
SYNTHETIC_CSV = """household_id,psu_code,respondent_age,gender,female_headed_hh,monthly_wage_inr,schooling_years,village_name,malaria_rdt_positive,survey_wave_year
H001,PSU42,34,1,0,18500,10,Village_A,0,2024
H002,PSU42,29,2,1,22000,12,Village_B,1,2024
"""

GROUND_TRUTH = {
    "household_id": "identifier",
    "psu_code": "identifier",
    "respondent_age": "demographic",
    "gender": "demographic",
    "female_headed_hh": "household",
    "monthly_wage_inr": "income",
    "schooling_years": "education",
    "village_name": "geography",
    "malaria_rdt_positive": "health",
    "survey_wave_year": "survey_metadata",
}


def relaxed_domain_match(predicted: str, expected: str) -> bool:
    if predicted == expected:
        return True
    if expected in predicted:
        return True
    if predicted.startswith("dyn_"):
        body = predicted[4:]
        if body == expected or body.startswith(expected + "_"):
            return True
    return False


def _graph_stats(sg: dict) -> dict:
    nodes = sg.get("nodes") or []
    edges = sg.get("edges") or []
    if isinstance(edges, list):
        return {"node_count": len(nodes), "edge_records": len(edges)}
    if isinstance(edges, dict):
        n_pairs = sum(len(v) for v in edges.values()) // 2
        return {"node_count": len(nodes) if isinstance(nodes, list) else len(nodes or {}), "edge_pairs_adjacency": n_pairs}
    return {"node_count": 0, "edge_records": 0}


def _resolve_expected_ground_truth(all_gts: dict, csv_path: str) -> dict:
    if not isinstance(all_gts, dict) or not csv_path:
        return {}
    path = Path(csv_path)
    candidate_keys = [
        path.name, path.stem, path.as_posix(),
        str(csv_path).replace("\\", "/").split("/")[-1], str(csv_path),
    ]
    normalized = {str(key).strip().lower(): value for key, value in all_gts.items() if isinstance(value, dict)}
    for candidate in candidate_keys:
        resolved = normalized.get(str(candidate).strip().lower())
        if resolved:
            return resolved
    if len(normalized) == 1:
        return next(iter(normalized.values()))
    return {}


def direct_pipeline_benchmark(csv_path: str = None, dataset_domain: str = None, dump_path: Path | None = None) -> dict:
    _setup_paths()
    from semantic_mapping.semantic_pipeline import SemanticPipeline
    
    if csv_path and os.path.exists(csv_path):
        import pandas as pd
        df = pd.read_csv(csv_path, nrows=0)
        columns = list(df.columns)
        
        gt_file = _repo_root() / "test_data" / "ground_truth.json"
        if gt_file.exists():
            try:
                with open(gt_file, 'r', encoding='utf-8') as f:
                    all_gts = json.load(f)
                expected_gt = _resolve_expected_ground_truth(all_gts, csv_path)
            except (OSError, JSONDecodeError) as exc:
                print(f"⚠️ Could not read ground_truth.json ({exc}).")
                expected_gt = {}
        else:
            expected_gt = {}
            
        if not expected_gt:
            print(f"⚠️ Answer key for '{Path(csv_path).name}' not found. Falling back to synthetic defaults.")
            expected_gt = GROUND_TRUTH
    else:
        reader = csv.DictReader(io.StringIO(SYNTHETIC_CSV))
        columns = list(reader.fieldnames or [])
        expected_gt = GROUND_TRUTH

    pipeline = SemanticPipeline()
    print(f"🚀 Running Semantic Pipeline (Waterfall Architecture)...")
    if dataset_domain:
        print(f"🧠 Injecting Context: '{dataset_domain}'")

    t0 = time.perf_counter()
    out = pipeline.run(columns, dataset_domain=dataset_domain)
    wall_s = time.perf_counter() - t0

    if dump_path:
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    mapping = out.get("semantic_mapping") or {}
    exact_ok = 0
    relaxed_ok = 0
    
    # Waterfall Metrics Tracking
    gatekeeper_locks = 0
    dynamic_fallbacks = 0
    uncorrelated_sinks = 0
    
    rows = []
    
    for col in columns:
        expected = expected_gt.get(col, "unknown_gt")
        details = mapping.get(col) or {}
        pred = details.get("domain") or ""
        conf = details.get("confidence", 0.0)
        
        e_ok = pred == expected
        r_ok = relaxed_domain_match(pred, expected)
        exact_ok += int(e_ok)
        relaxed_ok += int(r_ok)
        
        # Track Waterfall Behavior
        if pred == "uncorrelated":
            uncorrelated_sinks += 1
        elif conf >= 0.99:
            gatekeeper_locks += 1
        else:
            dynamic_fallbacks += 1

        rows.append({
            "column": col,
            "expected_domain": expected,
            "predicted_domain": pred,
            "exact_match": e_ok,
            "relaxed_match": r_ok,
            "confidence": conf,
        })

    n = len(columns)
    clusters = out.get("clusters") or []
    sg = out.get("schema_graph") or {}
    audit = out.get("audit_records") or []
    timings_hint = [{"step": rec.get("step"), "event": rec.get("event")} for rec in audit]

    return {
        "mode": "direct_semantic_pipeline",
        "wall_time_seconds": round(wall_s, 4),
        "column_count": n,
        "dataset_context": out.get("dataset_context"),
        "waterfall_metrics": {
            "phase_1_gatekeeper_locks": gatekeeper_locks,
            "phase_2_dynamic_fallbacks": dynamic_fallbacks,
            "phase_3_uncorrelated_sinks": uncorrelated_sinks
        },
        "accuracy": {
            "exact_match_rate": round(exact_ok / max(n, 1), 4),
            "exact_matches": exact_ok,
            "relaxed_match_rate": round(relaxed_ok / max(n, 1), 4),
            "relaxed_matches": relaxed_ok,
        },
        "per_column": rows,
        "clustering_benchmarks": {
            "num_clusters": len(clusters),
            "clusters_summary": clusters,
            "avg_support_score": round(
                sum(float(c.get("support_score", 0)) for c in clusters) / max(len(clusters), 1), 4
            ),
        },
        "graph_benchmarks": _graph_stats(sg),
        "priority_dependency_count": sum(
            len(v) if isinstance(v, (list, dict)) else 0 for v in (out.get("priority_dependencies") or {}).values()
        ),
        "audit_steps": timings_hint,
    }


def http_upload_analyze_benchmark(sqlite_path: Path, dump_json: Path | None) -> dict:
    os.environ["DATABASE_URL"] = f"sqlite:///{sqlite_path.as_posix()}"
    os.environ.setdefault("UPLOAD_STORAGE_PATH", str(_repo_root() / "storage" / "uploads"))
    os.environ.setdefault("REPORT_STORAGE_PATH", str(_repo_root() / "storage" / "reports"))
    _setup_paths()
    from auth.utils import hash_password
    from database.database import Base, SessionLocal, engine
    from database.models import User
    from fastapi.testclient import TestClient

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        db.merge(User(id=1, email="benchmark@statathon.local", password=hash_password("bench-secret")))
        db.commit()
    finally:
        db.close()

    from main import app
    client = TestClient(app)

    t_upload = time.perf_counter()
    up = client.post("/datasets/upload", files={"file": ("synthetic_survey.csv", SYNTHETIC_CSV.encode("utf-8"), "text/csv")})
    upload_s = time.perf_counter() - t_upload
    up.raise_for_status()
    dataset_id = up.json()["dataset_id"]

    t_analyze = time.perf_counter()
    an_resp = client.post(f"/analysis/{dataset_id}/analyze")
    analyze_s = time.perf_counter() - t_analyze
    if an_resp.status_code != 200:
        return {"mode": "http_testclient", "error": an_resp.text, "status_code": an_resp.status_code, "upload_seconds": round(upload_s, 4)}
    analysis_id = an_resp.json()["analysis_id"]

    t_res = time.perf_counter()
    res = client.get(f"/analysis/{analysis_id}/results")
    results_s = time.perf_counter() - t_res
    res.raise_for_status()
    payload = res.json()

    if dump_json:
        dump_json.parent.mkdir(parents=True, exist_ok=True)
        dump_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    mapping = _semantic_mapping_to_dict(payload)
    columns = list(GROUND_TRUTH.keys())
    exact_ok = relaxed_ok = 0
    rows = []
    for col in columns:
        expected = GROUND_TRUTH[col]
        pred = (mapping.get(col) or {}).get("domain") or ""
        e_ok = pred == expected
        r_ok = relaxed_domain_match(pred, expected)
        exact_ok += int(e_ok)
        relaxed_ok += int(r_ok)
        rows.append({"column": col, "expected_domain": expected, "predicted_domain": pred, "exact_match": e_ok, "relaxed_match": r_ok})
    n = len(columns)

    return {
        "mode": "http_testclient",
        "dataset_id": dataset_id,
        "analysis_id": analysis_id,
        "timings_seconds": {"upload": round(upload_s, 4), "analyze": round(analyze_s, 4), "fetch": round(results_s, 4)},
        "dataset_context": payload.get("dataset_context"),
        "accuracy": {"exact_match_rate": round(exact_ok / n, 4), "relaxed_match_rate": round(relaxed_ok / n, 4)},
        "per_column": rows,
    }

def _semantic_mapping_to_dict(payload: dict) -> dict[str, dict]:
    raw = payload.get("semantic_mapping") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {row["column"]: row for row in raw if isinstance(row, dict) and row.get("column") is not None}
    return {}

def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic layer benchmark")
    parser.add_argument("--dataset", type=str, default=None, help="Path to the test CSV file.")
    parser.add_argument("--domain", type=str, default=None, help="Context of the dataset (e.g., 'Economics')")
    parser.add_argument("--http", action="store_true", help="Run FastAPI upload → analyze")
    parser.add_argument("--dump-json", type=Path, default=None, help="Write raw JSON to this path")
    args = parser.parse_args()

    if args.http:
        tmp = Path(tempfile.mkdtemp(prefix="statathon_bench_")) / "bench.db"
        report = http_upload_analyze_benchmark(tmp, args.dump_json)
    else:
        report = direct_pipeline_benchmark(args.dataset, args.domain, args.dump_json)

    print(json.dumps(report, indent=2, default=str))

if __name__ == "__main__":
    main()