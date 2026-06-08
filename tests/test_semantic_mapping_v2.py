"""
V2 semantic mapping smoke test (new Qdrant-backed pipeline).

Exercises the production pipeline on a real sample CSV and asserts structural
correctness of the FINAL OUTPUT — it does NOT assert memorized domain names, so
it stays valid as the registries evolve. LLM is disabled here for determinism;
embeddings use whichever provider is available (BGE-M3 locally or Gemini).

Run from repo root:
  .\.venv\Scripts\python.exe .\tests\test_semantic_mapping_v2.py
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

import pandas as pd

from semantic_mapping_v2.pipeline import SemanticPipelineV2

_CSV = _REPO_ROOT / "test_data" / "unified_energy_reserves_dataset.csv"
_OUTPUT_KEYS = {
    "semantic_mapping", "column_normalization", "domains", "dynamic_domains",
    "clusters", "cluster_confidence", "usecase",
    "schema_graph", "knowledge_graph", "meta",
}


def test_v2_pipeline_structure() -> dict:
    """Run the pipeline on a real CSV and validate the output contract."""
    df = pd.read_csv(_CSV).head(200)
    pipeline = SemanticPipelineV2(use_llm=False)
    result = pipeline.analyze(
        df, dataset_id="test_energy_001", dataset_name="Energy Reserves Test"
    )

    # 1. Output contract.
    missing = _OUTPUT_KEYS - set(result)
    assert not missing, f"missing output keys: {missing}"

    # 2. Every column is mapped (now keyed by the canonical normalized name),
    #    with provenance back to the raw header via column_normalization.
    mapping = result["semantic_mapping"]
    colnorm = result["column_normalization"]
    assert len(mapping) == len(df.columns), "every column must be mapped"
    assert len(colnorm) == len(df.columns), "column_normalization must cover every column"
    raw_seen = {str(r["original_name"]) for r in colnorm}
    canon_seen = {str(r["canonical_name"]) for r in colnorm}
    assert raw_seen == set(map(str, df.columns)), "column_normalization must map every raw header"
    assert canon_seen == set(mapping), "canonical names must match the mapping keys"
    for col, m in mapping.items():
        assert "domain" in m and "confidence" in m and "source" in m, col
        assert 0.0 <= m["confidence"] <= 1.0, f"{col} confidence out of range"
        assert m.get("original_name"), f"{col} missing original_name provenance"
        assert m.get("display_name"), f"{col} missing display_name"

    # 3. Usecase detected (energy expected for this CSV).
    uc = result["usecase"]
    assert uc["usecase"], "usecase must be set"
    print(f"usecase: {uc['usecase']} ({uc['confidence']:.2f})")

    # 4. Clusters cover every column exactly once (by canonical name).
    clustered_cols = [c for cl in result["clusters"].values() for c in cl["columns"]]
    assert sorted(clustered_cols) == sorted(mapping), "clusters must cover all columns once"
    assert set(result["clusters"]) == set(result["cluster_confidence"])

    # 5. Schema graph + KG are well-formed.
    assert "nodes" in result["schema_graph"] and "edges" in result["schema_graph"]
    kg = result["knowledge_graph"]
    assert kg["stats"]["node_count"] == len(kg["nodes"])
    assert kg["stats"]["column_count"] == len(df.columns)

    # 6. Qdrant was actually used for the static registry.
    assert result["meta"]["qdrant_static_ready"] is True, "Qdrant static registry must be seeded"

    print(
        f"OK: {len(mapping)} cols, {len(result['clusters'])} clusters, "
        f"provider={result['meta']['embedding_provider']}, "
        f"static={result['meta']['static_domains']}"
    )
    return result


if __name__ == "__main__":
    test_v2_pipeline_structure()
    print("\nAll structural checks passed.")
