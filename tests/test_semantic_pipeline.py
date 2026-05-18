import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import numpy as np
import pytest

import semantic_mapping.semantic_pipeline as sp
from semantic_mapping.semantic_pipeline import SemanticPipeline
from semantic_mapping.column_preprocessor import ColumnPreprocessor
from semantic_mapping.similarity_engine import SimilarityEngine
from semantic_mapping.context_inference import ContextInference
from semantic_mapping.dataset_context_inferencer import DatasetContextInferencer
from audit.audit_logger import AuditLogger


class DummyVectorStore:
    def __init__(self, cache_dir: str | None = None):
        self._storage = {}
        self.cache_dir = cache_dir

    def has_embedding(self, text: str) -> bool:
        return text in self._storage

    def get_embedding(self, text: str) -> np.ndarray:
        return self._storage[text]

    def store_embedding(self, text: str, vector: np.ndarray) -> None:
        self._storage[text] = vector


class FakeBertEmbedder:
    def __init__(self, model_name=None, vector_store=None):
        self._store = vector_store
        self._cache: dict[str, np.ndarray] = {}
        self.vocab = [
            "age",
            "gender",
            "income",
            "salary",
            "health",
            "hospital",
            "blood",
            "pressure",
            "marks",
            "education",
            "district",
            "household",
            "survey",
            "number",
            "level",
            "year",
            "mobile",
            "internet",
            "index",
            "value",
            "score",
            "other",
        ]

    def _vector_for_text(self, text: str) -> np.ndarray:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        known = set(self.vocab[:-1])
        counts = [float(tokens.count(token)) for token in self.vocab[:-1]]
        unknown_count = sum(1 for token in tokens if token not in known)
        counts.append(float(unknown_count))
        if not any(counts):
            counts[-1] = 1.0
        return np.array(counts, dtype=float)

    def embed_text(self, text: str) -> np.ndarray:
        if text in self._cache:
            return self._cache[text]
        if self._store and self._store.has_embedding(text):
            result = self._store.get_embedding(text)
            self._cache[text] = result
            return result
        vector = self._vector_for_text(text)
        self._cache[text] = vector
        if self._store:
            self._store.store_embedding(text, vector)
        return vector

    def embed_batch(self, texts: list[str]) -> dict[str, np.ndarray]:
        return {text: self.embed_text(text) for text in texts}

    def embed_dict(self, mapping: dict[str, str]) -> dict[str, np.ndarray]:
        return {key: self.embed_text(value) for key, value in mapping.items()}

    def set_vector_store(self, vector_store):
        self._store = vector_store

    def clear_cache(self):
        self._cache.clear()


def inject_fake_embeddings(monkeypatch):
    monkeypatch.setattr(sp, "VectorStore", DummyVectorStore)
    monkeypatch.setattr(sp, "BertEmbedder", FakeBertEmbedder)


def build_mock_pipeline(monkeypatch, tmp_path: Path) -> SemanticPipeline:
    inject_fake_embeddings(monkeypatch)
    pipeline = SemanticPipeline(vector_cache_dir=str(tmp_path / "cache"))
    pipeline.audit = AuditLogger(logfile=str(tmp_path / "audit.json"))
    return pipeline


def print_domain_predictions(result: dict) -> None:
    print("\n=== DEBUG: Domain Predictions ===")
    for column, info in result.get("semantic_mapping", {}).items():
        scores = info.get("top_domain_scores", {})
        score_list = ", ".join(f"{name}:{score:.3f}" for name, score in scores.items())
        print(
            f"{column}: normalized={info.get('normalized_name')} domain={info.get('domain')} "
            f"confidence={info.get('confidence', 0):.4f} top_scores=[{score_list}]"
        )


def print_audit_steps(result: dict, limit: int = 20) -> None:
    print("\n=== DEBUG: Audit Steps ===")
    for record in result.get("audit_records", [])[:limit]:
        step = record.get("step", "n/a")
        event = record.get("event")
        print(f"step={step} event={event} data={json.dumps(record.get('data', {}), default=str)}")


def debug_assert(condition: bool, message: str, result: dict) -> None:
    if not condition:
        print_domain_predictions(result)
        print_audit_steps(result)
        raise AssertionError(message)


def assert_output_structure(result: dict, column_count: int) -> None:
    debug_assert(
        set(result.keys()) == {
            "dataset_context",
            "semantic_mapping",
            "clusters",
            "priority_dependencies",
            "schema_graph",
            "column_cluster_map",
            "audit_records",
        },
        "output keys mismatch",
        result,
    )
    debug_assert(isinstance(result["dataset_context"], dict), "dataset_context must be dict", result)
    debug_assert(isinstance(result["semantic_mapping"], dict), "semantic_mapping must be dict", result)
    debug_assert(len(result["semantic_mapping"]) == column_count, "semantic_mapping size mismatch", result)
    debug_assert(isinstance(result["clusters"], list), "clusters must be list", result)
    debug_assert(isinstance(result["priority_dependencies"], dict), "priority_dependencies must be dict", result)
    debug_assert(isinstance(result["schema_graph"], dict), "schema_graph must be dict", result)
    debug_assert(isinstance(result["column_cluster_map"], dict), "column_cluster_map must be dict", result)
    debug_assert(isinstance(result["audit_records"], list), "audit_records must be list", result)


def test_column_preprocessor_normalization():
    assert ColumnPreprocessor.normalize_column("AGE_yrs") == "age yrs"
    assert ColumnPreprocessor.normalize_column("inc_lvl$") == "inc lvl"
    tokens = ColumnPreprocessor.extract_tokens("bp_sys_val")
    assert tokens == ["bp", "sys", "val"]


def test_similarity_keyword_boost():
    boost = SimilarityEngine.compute_keyword_boost(["age", "income", "salary"], ["income", "salary", "wage"])
    assert boost == pytest.approx(2.0 / 3.0, rel=1e-6)


def test_pipeline_normal_input(monkeypatch, tmp_path: Path):
    pipeline = build_mock_pipeline(monkeypatch, tmp_path)
    columns = ["age", "gender", "income"]
    result = pipeline.run(columns)

    assert_output_structure(result, column_count=3)
    for column in columns:
        info = result["semantic_mapping"][column]
        debug_assert("domain" in info, f"missing domain for {column}", result)
        debug_assert("confidence" in info, f"missing confidence for {column}", result)
        debug_assert("normalized_name" in info, f"missing normalized_name for {column}", result)
        debug_assert(0.0 <= info["confidence"] <= 1.0, f"confidence out of range for {column}", result)


def test_pipeline_handles_empty_input(monkeypatch, tmp_path: Path):
    pipeline = build_mock_pipeline(monkeypatch, tmp_path)
    result = pipeline.run([])

    assert_output_structure(result, column_count=0)
    debug_assert(result["semantic_mapping"] == {}, "semantic_mapping should be empty for empty input", result)
    debug_assert(result["column_cluster_map"] == {}, "column_cluster_map should be empty for empty input", result)
    debug_assert(result["clusters"] == [], "clusters should be empty for empty input", result)
    debug_assert(result["schema_graph"] == {"nodes": [], "edges": []}, "schema_graph should be empty for empty input", result)


def test_pipeline_ambiguous_columns(monkeypatch, tmp_path: Path):
    pipeline = build_mock_pipeline(monkeypatch, tmp_path)
    columns = ["value", "score", "index"]
    result = pipeline.run(columns)

    assert_output_structure(result, column_count=3)
    for column in columns:
        info = result["semantic_mapping"][column]
        debug_assert("domain" in info, f"missing domain for {column}", result)
        debug_assert(0.0 <= info["confidence"] <= 1.0, f"confidence out of range for {column}", result)
        debug_assert(info["normalized_name"], f"normalized_name empty for {column}", result)


def test_pipeline_mixed_domain_columns(monkeypatch, tmp_path: Path):
    pipeline = build_mock_pipeline(monkeypatch, tmp_path)
    columns = ["salary", "blood_pressure", "marks"]
    result = pipeline.run(columns)

    assert_output_structure(result, column_count=3)
    domains = {result["semantic_mapping"][column]["domain"] for column in columns}
    debug_assert(len(domains) >= 2, "expected at least two domains for mixed input", result)
    for column in columns:
        info = result["semantic_mapping"][column]
        debug_assert(0.0 <= info["confidence"] <= 1.0, f"confidence out of range for {column}", result)


def test_pipeline_noisy_columns(monkeypatch, tmp_path: Path):
    pipeline = build_mock_pipeline(monkeypatch, tmp_path)
    columns = ["usr_age_01", "bp_sys_val", "inc_lvl$"]
    result = pipeline.run(columns)

    assert_output_structure(result, column_count=3)
    expected_normalized = {
        "usr_age_01": "usr age 01",
        "bp_sys_val": "bp sys val",
        "inc_lvl$": "inc level",
    }
    for column, expected in expected_normalized.items():
        info = result["semantic_mapping"][column]
        debug_assert(info["normalized_name"] == expected, f"normalized_name mismatch for {column}", result)
        debug_assert(0.0 <= info["confidence"] <= 1.0, f"confidence out of range for {column}", result)


def test_debug_helpers_integration(monkeypatch, tmp_path: Path, capsys):
    pipeline = build_mock_pipeline(monkeypatch, tmp_path)
    result = pipeline.run(["age", "income"])

    print_domain_predictions(result)
    print_audit_steps(result, limit=3)
    captured = capsys.readouterr()

    assert "DEBUG: Domain Predictions" in captured.out
    assert "DEBUG: Audit Steps" in captured.out
    assert "age" in captured.out


def test_pipeline_runtime_benchmark(monkeypatch, tmp_path: Path):
    pipeline = build_mock_pipeline(monkeypatch, tmp_path)
    columns = ["age", "gender", "income", "salary", "bp_sys_val"]

    start = time.perf_counter()
    result = pipeline.run(columns)
    elapsed = time.perf_counter() - start

    assert_output_structure(result, column_count=len(columns))
    assert elapsed < 1.0, f"Pipeline runtime too slow: {elapsed:.3f}s"
    print(f"Pipeline runtime: {elapsed:.4f}s")

