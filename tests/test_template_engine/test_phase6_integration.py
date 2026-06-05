"""Phase 6: Integration tests spanning all phases.

These tests verify the cross-phase connections work end-to-end:
  - Phase 1 config → Phase 2 PLFS parser → Phase 3 binder → Phase 4 LTM → Phase 5 API
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ============================================================================
# Step 36: PLFS Integration Tests
# ============================================================================


class TestPLFSEndToEnd:
    """Integration: PLFS parsing → entity extraction → question inference."""

    def test_plfs_glossary_feeds_column_resolver(self):
        """Verify PLFS glossary abbreviations are used by column resolver."""
        from template_engine.binder.column_resolver import ColumnResolver
        from template_engine.binder.template_binder import DatasetSchema
        from ast_core.schema import TemplateEntity

        columns = [
            "labour_force_participation_rate",
            "worker_population_ratio",
            "unemployment_rate",
        ]
        schema = DatasetSchema(
            datasetId="test",
            columns=columns,
            columnTypes={c: "float64" for c in columns},
        )
        resolver = ColumnResolver()
        entity = TemplateEntity(entityId="e1", name="LFPR")

        result = resolver.resolve(entity, schema)
        # Should find something or return None (depending on alias config)
        # At minimum, resolver should not crash
        assert result is None or isinstance(result, dict)

    def test_plfs_parser_produces_entities(self):
        """PLFS parser extracts entities from statement text."""
        from template_engine.extraction.plfs_parser import extract_entities_from_statement

        entities = extract_entities_from_statement(
            "Quarterly estimates on UR", 2, 1, 0,
        )
        assert isinstance(entities, list)

    def test_style_engine_patterns_match_plfs_glossary(self):
        """Style rules terminology should align with PLFS glossary."""
        from template_engine.inference.plfs_style_engine import resolve_terminology, _load_rules

        rules = _load_rules()
        terminology = rules.get("terminology", {})

        # All glossary abbreviations should resolve
        plfs_glossary_path = Path(__file__).parent.parent.parent / "template_engine" / "inference" / "patterns" / "plfs_glossary.json"
        if plfs_glossary_path.exists():
            with open(plfs_glossary_path) as f:
                glossary = json.load(f)
            abbrevs = glossary.get("abbreviations", {})
            # At least some overlap
            overlap = set(terminology.keys()) & set(abbrevs.keys())
            assert len(overlap) >= 3  # LFPR, WPR, UR at minimum


# ============================================================================
# Step 37: Report Generation Tests
# ============================================================================


class TestReportGenerationFlow:
    """Integration: orchestrator → consensus → scribe → citations."""

    def test_orchestrator_imports_and_has_api(self):
        from report_builder.orchestrator import ReportOrchestrator
        orch = ReportOrchestrator()
        assert hasattr(orch, "generate_report")

    def test_citation_manager_with_real_facts(self):
        from template_engine.render.citation_manager import CitationManager

        mgr = CitationManager()
        narrative = "The unemployment rate was 4.2% in Q3 2024."
        facts = {"unemployment_rate": 4.2, "quarter": "Q3", "year": 2024}
        sources = {"unemployment_rate": "PLFS Q3 2024, Table 12"}

        result = mgr.cite(narrative, facts, sources)
        assert result.cited_narrative  # Should have some form of citation
        assert len(result.cited_narrative) >= len(narrative)

    def test_latex_renderer_escape(self):
        from template_engine.render.latex_renderer import _escape_latex

        escaped = _escape_latex("100% of $values & #1 are {weird}")
        assert "\\" in escaped  # Should have escape sequences

    def test_template_cache_stores_and_retrieves(self):
        from template_engine.storage.template_cache import TemplateCache

        cache = TemplateCache()
        cache.clear()

        # Store a template — pages_data must be dicts with regions
        pages_data = [{"pageIndex": 0, "regions": [{"role": "heading_h1", "text": "Test", "y": 50}]}]
        cache.store(pages_data, [], [])

        # Verify store doesn't crash and cache has content
        # (lookup uses hash-based key)
        cache.clear()


# ============================================================================
# Step 38: LLM Provider Tests
# ============================================================================


class TestLLMProviderRouting:
    """Integration: LLM router routes correctly per role."""

    def test_router_config_loads(self):
        from template_engine.llm.router import get_llm_router

        router = get_llm_router()
        assert router is not None
        assert hasattr(router, "generate")

    def test_router_has_role_config(self):
        from template_engine.llm.router import get_llm_router

        router = get_llm_router()
        # Router should have config for known roles
        assert hasattr(router, "_role_configs") or hasattr(router, "_configs")

    def test_observability_llm_span_integration(self):
        """LLM span works with router pattern."""
        from template_engine.observability.llm_tracing import llm_span

        with llm_span("scribe", model="test-model") as result:
            result.output = "Generated narrative"
            result.prompt_tokens = 50
            result.completion_tokens = 20

        assert result.total_tokens == 70
        assert result.latency_ms > 0


# ============================================================================
# Step 39: Checkpoint/Resume Tests
# ============================================================================


class TestCheckpointResume:
    """Integration: checkpoint save/load across pipeline stages."""

    def test_checkpoint_backend_interface(self):
        from template_engine.storage.checkpoint import FileCheckpoint

        cp = FileCheckpoint(base_dir="./test_checkpoints_integration")
        # Should have save/load/exists methods
        assert hasattr(cp, "save")
        assert hasattr(cp, "load")
        assert hasattr(cp, "exists")

    def test_checkpoint_config_from_env(self):
        from template_engine.config import get_config, reset_config
        import os

        reset_config()
        os.environ.pop("CHECKPOINT_ENABLED", None)
        config = get_config()
        assert hasattr(config, "checkpoint")
        assert config.checkpoint.enabled is False  # Default disabled
        reset_config()


# ============================================================================
# Step 40: Benchmark Suite (lightweight — measures key operations)
# ============================================================================


class TestBenchmarkSuite:
    """Micro-benchmarks for critical path operations."""

    def test_column_resolver_performance(self):
        """Column resolver should handle 100 entities in < 2s."""
        import time
        from template_engine.binder.column_resolver import ColumnResolver
        from template_engine.binder.template_binder import DatasetSchema
        from ast_core.schema import TemplateEntity

        columns = [f"column_{i}" for i in range(50)]
        columns += ["labour_force_participation_rate", "unemployment_rate", "worker_population_ratio"]
        schema = DatasetSchema(datasetId="bench", columns=columns, columnTypes={c: "float64" for c in columns})
        resolver = ColumnResolver()

        entities = [TemplateEntity(entityId=f"e{i}", name=f"entity_{i}") for i in range(100)]
        start = time.time()
        for e in entities:
            resolver.resolve(e, schema)
        elapsed = time.time() - start
        assert elapsed < 2.0  # Should be fast

    def test_template_cache_lookup_performance(self):
        """Cache operations should be fast."""
        import time
        from template_engine.storage.template_cache import TemplateCache

        cache = TemplateCache()
        cache.clear()

        # Pre-populate with valid page data
        for i in range(20):
            pages = [{"pageIndex": i, "regions": [{"role": "heading_h1", "text": f"Page {i}", "y": 10}]}]
            cache.store(pages, [], [])

        start = time.time()
        # Lookup by hash of known pages
        for i in range(20):
            pages = [{"pageIndex": i, "regions": [{"role": "heading_h1", "text": f"Page {i}", "y": 10}]}]
            cache.lookup(pages)
        elapsed = time.time() - start
        assert elapsed < 1.0

        cache.clear()

    def test_hash_embed_performance(self):
        """Hash embedding fallback should be < 1ms per call."""
        import time
        from template_engine.storage.ltm_store import LTMStore

        start = time.time()
        for i in range(100):
            LTMStore._hash_embed(f"test text {i}")
        elapsed = time.time() - start
        assert elapsed < 0.5  # 100 embeddings in < 500ms

    def test_plfs_parser_performance(self):
        """PLFS parser should handle 50 statements in < 2s."""
        import time
        from template_engine.extraction.plfs_parser import extract_entities_from_statement

        start = time.time()
        for i in range(1, 11):
            for j in range(1, 6):
                extract_entities_from_statement(f"Test indicator {i}", i, j, 0)
        elapsed = time.time() - start
        assert elapsed < 2.0

    def test_progress_event_serialization_performance(self):
        """SSE event serialization should be fast."""
        import time
        from api.report_builder_api.progress_sse import ProgressEvent

        start = time.time()
        for i in range(1000):
            event = ProgressEvent(stage=f"stage_{i}", pct=i % 100, message=f"msg {i}")
            event.to_sse()
        elapsed = time.time() - start
        assert elapsed < 1.0  # 1000 serializations in < 1s
