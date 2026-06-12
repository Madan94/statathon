r"""
Manual test harness for Semantic Mapping & Domain Clustering V2.

Runs the production pipeline on the repo's sample CSVs and prints a structured
summary (usecase, per-column domain mapping, clusters, KG stats). This only
*exercises* the pipeline on real data — it does not tune anything to the CSVs.

Usage:
    .\.venv\Scripts\python.exe scripts\test_semantic_v2.py
    .\.venv\Scripts\python.exe scripts\test_semantic_v2.py --no-llm
    .\.venv\Scripts\python.exe scripts\test_semantic_v2.py --only energy
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "model"))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

from semantic_mapping_v2 import SemanticPipelineV2  # noqa: E402

DATASETS = [
    {"key": "energy", "path": REPO_ROOT / "test_data" / "unified_energy_reserves_dataset.csv",
     "name": "Unified Energy Reserves", "expect": "energy"},
    {"key": "labour", "path": REPO_ROOT / "test_data" / "MoSPI Dataset Example.csv",
     "name": "MoSPI PLFS Labour", "expect": "labour"},
    {"key": "industry", "path": REPO_ROOT / "test_data" / "Economics - MoSPI.csv",
     "name": "MoSPI CPI Economics", "expect": "industry"},
    {"key": "consumption", "path": REPO_ROOT / "tests" / "mospi_mock_survey_data.csv",
     "name": "MoSPI HCES Survey", "expect": "consumption"},
]

MAX_ROWS = int(os.getenv("SEMV2_TEST_MAX_ROWS", "400"))


def _fmt_pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def run_one(pipe: SemanticPipelineV2, ds: dict) -> dict:
    path: Path = ds["path"]
    print("\n" + "=" * 78)
    print(f"DATASET: {ds['name']}  ({path.name})")
    print("=" * 78)
    if not path.exists():
        print(f"  !! missing file: {path}")
        return {}

    df = pd.read_csv(path)
    if len(df) > MAX_ROWS:
        df = df.head(MAX_ROWS)
    print(f"  rows={len(df)}  columns={len(df.columns)}")

    t0 = time.time()
    result = pipe.analyze(df, dataset_id=ds["key"], dataset_name=ds["name"])
    elapsed = time.time() - t0

    uc = result["usecase"]
    meta = result["meta"]
    print(f"\n  USECASE: {uc['usecase']}  conf={_fmt_pct(uc['confidence'])}  "
          f"source={uc['source']}  (expected {ds['expect']})")
    print(f"  embeddings: {meta['embedding_provider']} dim={meta['embedding_dim']}  "
          f"| static={meta['static_domains']} dynamic={meta['dynamic_domains']} "
          f"llm_used={meta['llm_used']}  qdrant_static={meta['qdrant_static_ready']}")

    print("\n  SEMANTIC MAPPING (column -> domain):")
    for col, m in result["semantic_mapping"].items():
        print(f"    {col:<26} -> {m['domain']:<28} {_fmt_pct(m['confidence'])} "
              f"[{m['source']}/{m['dtype']}]")

    print("\n  CLUSTERS:")
    for cid, cl in result["clusters"].items():
        cols = ", ".join(cl["columns"])
        print(f"    {cid} '{cl['cluster_name']}' conf={_fmt_pct(cl['cluster_confidence'])} "
              f"purity={_fmt_pct(cl['purity'])} dom={cl['dominant_domain']}")
        print(f"        cols: {cols}")

    kg = result["knowledge_graph"]["stats"]
    sg = result["schema_graph"]
    print(f"\n  KG: nodes={kg['node_count']} edges={kg['edge_count']} "
          f"domains={kg['domain_count']} clusters={kg['cluster_count']} "
          f"| schema edges={len(sg['edges'])} | neo4j={result['knowledge_graph']['neo4j_synced']}")
    print(f"  elapsed: {elapsed:.1f}s")

    return {
        "usecase_ok": uc["usecase"] == ds["expect"],
        "n_uncorrelated": sum(1 for m in result["semantic_mapping"].values()
                              if m["source"] == "uncorrelated"),
        "n_cols": len(result["semantic_mapping"]),
        "n_clusters": len(result["clusters"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="disable dynamic domains + LLM fallback")
    ap.add_argument("--only", default=None, help="run a single dataset by key")
    args = ap.parse_args()

    pipe = SemanticPipelineV2(use_llm=not args.no_llm)
    print(f"Embedder: provider={pipe.embedder.provider} model={pipe.embedder.model_name} "
          f"dim={pipe.embedder.dim} signature={pipe.embedder.signature}")
    print(f"LLM dynamic/fallback: {'OFF' if args.no_llm else 'ON'}")

    summary = []
    for ds in DATASETS:
        if args.only and ds["key"] != args.only:
            continue
        try:
            summary.append((ds["key"], run_one(pipe, ds)))
        except Exception as exc:  # noqa: BLE001
            import traceback
            print(f"  !! ERROR on {ds['key']}: {exc}")
            traceback.print_exc()
            summary.append((ds["key"], {"error": str(exc)}))

    print("\n" + "#" * 78)
    print("SUMMARY")
    print("#" * 78)
    for key, s in summary:
        if "error" in s:
            print(f"  {key:<12} ERROR: {s['error']}")
        else:
            print(f"  {key:<12} usecase_ok={s['usecase_ok']!s:<5} "
                  f"cols={s['n_cols']} uncorrelated={s['n_uncorrelated']} "
                  f"clusters={s['n_clusters']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
