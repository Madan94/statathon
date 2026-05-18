#!/usr/bin/env python3
"""
End-to-end semantic benchmark: synthetic labeled survey CSV → SemanticPipeline
(upload→analyze path optional via --http).

Ground truth is human-assigned base ontology labels; the pipeline may assign
runtime `dyn_*` domains — we report exact and relaxed (substring / dyn_ prefix) accuracy.
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _setup_paths() -> None:
    root = _repo_root()
    api = root / "api"
    for p in (str(root), str(api)):
        if p not in sys.path:
            sys.path.insert(0, p)


# Synthetic official-style survey: column names chosen to align with base domains in
# model/config/domain_definitions.json (still evaluated fairly against actual predictions).
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


def direct_pipeline_benchmark(dump_path: Path | None = None) -> dict:
    _setup_paths()
    from pipelines.semantic_runner import run_semantic_pipeline

    reader = csv.DictReader(io.StringIO(SYNTHETIC_CSV))
    columns = list(reader.fieldnames or [])

    t0 = time.perf_counter()
    out = run_semantic_pipeline(columns)
    wall_s = time.perf_counter() - t0

    if dump_path:
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    mapping = out.get("semantic_mapping") or {}
    exact_ok = 0
    relaxed_ok = 0
    rows = []
    for col in columns:
        expected = GROUND_TRUTH[col]
        pred = (mapping.get(col) or {}).get("domain") or ""
        e_ok = pred == expected
        r_ok = relaxed_domain_match(pred, expected)
        exact_ok += int(e_ok)
        relaxed_ok += int(r_ok)
        rows.append(
            {
                "column": col,
                "expected_domain": expected,
                "predicted_domain": pred,
                "exact_match": e_ok,
                "relaxed_match": r_ok,
                "confidence": (mapping.get(col) or {}).get("confidence"),
            }
        )

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
        "accuracy": {
            "exact_match_rate": round(exact_ok / n, 4),
            "exact_matches": exact_ok,
            "relaxed_match_rate": round(relaxed_ok / n, 4),
            "relaxed_matches": relaxed_ok,
            "note": "Relaxed counts predictions that equal the gold label, contain it as a substring, or use dyn_<gold>_…",
        },
        "per_column": rows,
        "clustering_benchmarks": {
            "num_clusters": len(clusters),
            "clusters_summary": clusters,
            "avg_support_score": round(
                sum(float(c.get("support_score", 0)) for c in clusters) / max(len(clusters), 1),
                4,
            ),
        },
        "graph_benchmarks": _graph_stats(sg),
        "priority_dependency_count": sum(
            len(v) if isinstance(v, (list, dict)) else 0 for v in (out.get("priority_dependencies") or {}).values()
        ),
        "audit_steps": timings_hint,
        "dumped_raw_pipeline": str(dump_path) if dump_path else None,
    }


def _semantic_mapping_to_dict(payload: dict) -> dict[str, dict]:
    raw = payload.get("semantic_mapping") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {
            row["column"]: row
            for row in raw
            if isinstance(row, dict) and row.get("column") is not None
        }
    return {}


def http_upload_analyze_benchmark(sqlite_path: Path, dump_json: Path | None) -> dict:
    os.environ["DATABASE_URL"] = f"sqlite:///{sqlite_path.as_posix()}"
    os.environ.setdefault("UPLOAD_STORAGE_PATH", str(_repo_root() / "storage" / "uploads"))
    os.environ.setdefault("REPORT_STORAGE_PATH", str(_repo_root() / "storage" / "reports"))

    _setup_paths()

    # Import after DATABASE_URL is set so engine binds to benchmark SQLite.
    from auth.utils import hash_password
    from database.database import Base, SessionLocal, engine
    from database.models import User
    from fastapi.testclient import TestClient

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        db.merge(
            User(id=1, email="benchmark@statathon.local", password=hash_password("bench-secret"))
        )
        db.commit()
    finally:
        db.close()

    from main import app

    client = TestClient(app)

    t_upload = time.perf_counter()
    up = client.post(
        "/datasets/upload",
        files={"file": ("synthetic_survey.csv", SYNTHETIC_CSV.encode("utf-8"), "text/csv")},
    )
    upload_s = time.perf_counter() - t_upload
    up.raise_for_status()
    dataset_id = up.json()["dataset_id"]

    t_analyze = time.perf_counter()
    an_resp = client.post(f"/analysis/{dataset_id}/analyze")
    analyze_s = time.perf_counter() - t_analyze
    if an_resp.status_code != 200:
        return {
            "mode": "http_testclient",
            "error": an_resp.text,
            "status_code": an_resp.status_code,
            "upload_seconds": round(upload_s, 4),
        }
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
        rows.append(
            {
                "column": col,
                "expected_domain": expected,
                "predicted_domain": pred,
                "exact_match": e_ok,
                "relaxed_match": r_ok,
            }
        )
    n = len(columns)

    return {
        "mode": "http_testclient",
        "dataset_id": dataset_id,
        "analysis_id": analysis_id,
        "timings_seconds": {
            "upload": round(upload_s, 4),
            "analyze_total_including_semantic": round(analyze_s, 4),
            "fetch_results": round(results_s, 4),
        },
        "dataset_context": payload.get("dataset_context"),
        "accuracy": {
            "exact_match_rate": round(exact_ok / n, 4),
            "relaxed_match_rate": round(relaxed_ok / n, 4),
        },
        "per_column": rows,
        "clusters": payload.get("clusters"),
        "schema_graph": payload.get("schema_graph"),
        "graph_benchmarks": _graph_stats(payload.get("schema_graph") or {}),
        "checkpoint_keys": list(payload.keys()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic layer benchmark")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run FastAPI upload → analyze → GET results (uses temporary SQLite DB)",
    )
    parser.add_argument(
        "--dump-json",
        type=Path,
        default=None,
        help="Write raw pipeline / results JSON to this path",
    )
    args = parser.parse_args()

    if args.http:
        tmp = Path(tempfile.mkdtemp(prefix="statathon_bench_")) / "bench.db"
        report = http_upload_analyze_benchmark(tmp, args.dump_json)
    else:
        report = direct_pipeline_benchmark(args.dump_json)

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
