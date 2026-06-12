r"""
Full pre-anomaly pipeline test on every tabular file in test_data/.

Stages (stops BEFORE anomaly detection):
  1. Load / convert dataset
  2. Schema inference + health summary
  3. Dataset intelligence profiling
  4. Semantic Mapping V2 (Gemini LLM, Groq fallback)
  5. AnalysisState build + schema blueprint
  6. Validation gate (context-aware rules)

Usage:
  python scripts/test_pre_anomaly_all_datasets.py
  python scripts/test_pre_anomaly_all_datasets.py --max-rows 500
  python scripts/test_pre_anomaly_all_datasets.py --no-llm
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "model"))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

# Tests must not depend on Neo4j cloud or burn Gemini embed quota on every file.
os.environ["NEO4J_ENABLED"] = "false"
os.environ.setdefault("SEMV2_EMBED_PROVIDER", "local")
os.environ["QDRANT_LOCAL_PATH"] = str(
    REPO_ROOT / "model" / "storage" / f"qdrant_preanomaly_{os.getpid()}"
)

import pandas as pd

from semantic_mapping_v2.qdrant_store import reset_client

from core.ingestion import health_summary, infer_schema
from core.rule_validator import normalize_schema
from pipelines.semantic_adapter import build_analysis_state
from pipelines.semantic_runner import run_semantic_pipeline
from pipelines.validation_gate import run_validation_gate
from profiling import build_dataset_intelligence_profiles, load_default_ontology
from scripts.testdata_io import (
    dedupe_by_content,
    discover_testdata_files,
    expected_usecase,
    load_tabular,
)

from semantic_mapping_v2.llm_client import llm_status


def _pct(n: float) -> str:
    return f"{100 * n:.1f}%"


def run_one(path: Path, *, max_rows: int, use_llm: bool) -> dict:
    rel = path.relative_to(REPO_ROOT / "test_data")
    t0 = time.time()
    result: dict = {
        "path": str(rel),
        "status": "pending",
    }
    try:
        df, kind = load_tabular(path, max_rows=max_rows)
        if df is None:
            result.update(status="skipped", load_kind=kind, reason=kind)
            return result

        if df.empty or len(df.columns) == 0:
            result.update(status="skipped", load_kind=kind, reason="empty_dataframe")
            return result

        schema = infer_schema(df)
        health = health_summary(df)
        ontology = load_default_ontology()
        ontology_dict = ontology if isinstance(ontology, dict) else {}
        column_profiles, dataset_profile = build_dataset_intelligence_profiles(
            df, ontology_dict if ontology_dict else None
        )

        semantic_bundle = run_semantic_pipeline(
            list(df.columns),
            column_profiles=column_profiles,
            df=df,
            dataset_id=str(rel).replace("\\", "/"),
            dataset_name=path.stem,
            filename=path.name,
            use_llm=use_llm,
        )

        state = build_analysis_state(
            dataset_id=1,
            analysis_id=1,
            pipeline_out=semantic_bundle,
            profiling_summary={"health": health, "schema": schema},
            column_profiles=column_profiles,
            dataset_profile=dataset_profile,
            static_domains=ontology_dict,
            dataset_metadata={"filename": path.name, "path": str(rel), "columns": list(df.columns)},
        )

        df_coerced = normalize_schema(df, schema)
        cols_meta = state.semantic_profile.get("columns") if isinstance(state.semantic_profile, dict) else {}
        gate = run_validation_gate(
            df_coerced,
            columns_meta=cols_meta,
            schema_graph=state.schema_graph,
            priority_dependencies=state.dependency_graph,
            column_profiles=column_profiles,
            unified_domains=semantic_bundle.get("unified_domains"),
            archetypes=(semantic_bundle.get("dataset_context") or {}).get("archetypes"),
            analysis_id=1,
        )

        mapping = semantic_bundle.get("semantic_mapping") or {}
        n_cols = len(mapping)
        confidences = [float(m.get("confidence", 0)) for m in mapping.values() if isinstance(m, dict)]
        uncorr = sum(
            1 for m in mapping.values()
            if isinstance(m, dict) and str(m.get("domain", "")).lower() == "uncorrelated"
        )
        llm_mapped = sum(
            1 for m in mapping.values()
            if isinstance(m, dict) and str(m.get("source", "")).lower() == "llm"
        )
        exp_uc = expected_usecase(path, list(df.columns))
        det_uc = (semantic_bundle.get("dataset_context") or {}).get("usecase")
        if not det_uc and semantic_bundle.get("semantic_v2_usecase"):
            det_uc = semantic_bundle["semantic_v2_usecase"].get("usecase")

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        mapped_rate = (n_cols - uncorr) / n_cols if n_cols else 0.0
        conf_rate = sum(1 for c in confidences if c >= 0.5) / n_cols if n_cols else 0.0
        usecase_ok = exp_uc is None or exp_uc == det_uc

        gate_summary = gate.get("summary") or {}
        approved = bool(gate_summary.get("approved", gate_summary.get("candidate_count", 0) == 0))

        result.update(
            status="ok",
            load_kind=kind,
            rows=len(df),
            columns=n_cols,
            usecase_detected=det_uc,
            usecase_expected=exp_uc,
            usecase_match=usecase_ok,
            mapped_rate=round(mapped_rate, 4),
            confident_rate=round(conf_rate, 4),
            avg_confidence=round(avg_conf, 4),
            uncorrelated=uncorr,
            llm_mapped=llm_mapped,
            clusters=len(semantic_bundle.get("clusters") or []),
            validation_rules=gate_summary.get("rules_discovered", 0),
            validation_fired=gate_summary.get("rules_fired", 0),
            validation_approved=approved,
            embedding_provider=(semantic_bundle.get("semantic_v2_meta") or {}).get("embedding_provider"),
            llm_used=(semantic_bundle.get("semantic_v2_meta") or {}).get("llm_used"),
            elapsed_sec=round(time.time() - t0, 2),
        )

        quality_ok = (
            mapped_rate >= 0.55
            and avg_conf >= 0.44
            and (exp_uc is None or usecase_ok)
        )
        result["quality_pass"] = quality_ok
        if not quality_ok:
            result["status"] = "weak_accuracy"

    except Exception as exc:
        result.update(
            status="error",
            error=str(exc),
            traceback=traceback.format_exc()[-800:],
            elapsed_sec=round(time.time() - t0, 2),
        )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=int(os.getenv("PREANOMALY_MAX_ROWS", "600")))
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--keep-dupes", action="store_true", help="do not dedupe identical files")
    ap.add_argument("--out", default=str(REPO_ROOT / "storage" / "reports" / "pre_anomaly_test_report.json"))
    args = ap.parse_args()

    reset_client()

    print("=" * 80)
    print("PRE-ANOMALY FULL TEST — test_data/")
    print(f"  max_rows={args.max_rows}  llm={not args.no_llm}")
    print(f"  qdrant_path={os.environ.get('QDRANT_LOCAL_PATH')}")
    print("  LLM:", json.dumps(llm_status()))
    print("=" * 80)

    paths = discover_testdata_files()
    if not args.keep_dupes:
        before = len(paths)
        paths = dedupe_by_content(paths)
        print(f"Discovered {before} files -> {len(paths)} unique after dedupe")

    results = []
    for i, p in enumerate(paths, 1):
        print(f"\n[{i}/{len(paths)}] {p.relative_to(REPO_ROOT)}")
        r = run_one(p, max_rows=args.max_rows, use_llm=not args.no_llm)
        reset_client()
        results.append(r)
        if r["status"] == "ok":
            print(
                f"  OK usecase={r['usecase_detected']} (exp={r['usecase_expected']}) "
                f"mapped={_pct(r['mapped_rate'])} conf={_pct(r['confident_rate'])} "
                f"avg={r['avg_confidence']:.2f} llm_cols={r['llm_mapped']} "
                f"val_approved={r['validation_approved']} {r['elapsed_sec']}s"
            )
        elif r["status"] == "weak_accuracy":
            print(
                f"  WEAK usecase={r.get('usecase_detected')} match={r.get('usecase_match')} "
                f"mapped={_pct(r.get('mapped_rate', 0))} avg={r.get('avg_confidence', 0):.2f}"
            )
        elif r["status"] == "skipped":
            print(f"  SKIP ({r.get('reason')})")
        else:
            print(f"  ERROR: {r.get('error', '')[:120]}")

    ok = sum(1 for r in results if r["status"] == "ok")
    weak = sum(1 for r in results if r["status"] == "weak_accuracy")
    skip = sum(1 for r in results if r["status"] == "skipped")
    err = sum(1 for r in results if r["status"] == "error")
    uc_ok = sum(1 for r in results if r.get("usecase_match") is True)
    uc_tested = sum(1 for r in results if r.get("usecase_expected"))

    report = {
        "summary": {
            "total": len(results),
            "ok": ok,
            "weak_accuracy": weak,
            "skipped": skip,
            "errors": err,
            "usecase_accuracy": round(uc_ok / uc_tested, 4) if uc_tested else None,
            "llm_status": llm_status(),
        },
        "results": results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print(f"  OK: {ok}  WEAK: {weak}  SKIP: {skip}  ERROR: {err}")
    if uc_tested:
        print(f"  Usecase accuracy: {uc_ok}/{uc_tested} ({_pct(uc_ok/uc_tested)})")
    print(f"  Report: {out_path}")
    print("=" * 80)

    reset_client()
    return 0 if err == 0 and weak == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
