"""Tests for Phase 4 (Observability + LTM) and Phase 5 (Dashboard API)."""
from __future__ import annotations

import json
import time
import asyncio
import pytest
from unittest.mock import patch, MagicMock


# ============================================================================
# PHASE 4 TESTS — Observability and LTM
# ============================================================================


class TestLLMTracing:
    """Step 25: LLM-specific tracing."""

    def test_llm_span_context_manager(self):
        from template_engine.observability.llm_tracing import llm_span, LLMSpanResult

        with llm_span("scribe", model="test-model", prompt="hello") as result:
            result.output = "world"
            result.prompt_tokens = 5
            result.completion_tokens = 3

        assert result.output == "world"
        assert result.total_tokens == 8
        assert result.latency_ms > 0
        assert result.role == "scribe"
        assert result.model == "test-model"

    def test_llm_span_error_handling(self):
        from template_engine.observability.llm_tracing import llm_span

        with pytest.raises(ValueError):
            with llm_span("verifier", model="m") as result:
                raise ValueError("test error")

        assert result.error == "test error"

    def test_trace_llm_call_decorator(self):
        from template_engine.observability.llm_tracing import trace_llm_call

        @trace_llm_call(role="inferrer", model="test")
        def my_llm_fn(prompt: str) -> str:
            return f"reply to {prompt}"

        output = my_llm_fn(prompt="hello")
        assert output == "reply to hello"


class TestLTMStore:
    """Step 26: Qdrant Cloud LTM."""

    def test_ltm_disabled_by_default(self):
        from template_engine.storage.ltm_store import LTMStore, LTMConfig

        config = LTMConfig(enabled=False)
        store = LTMStore(config)
        assert not store.is_available

    def test_store_correction_noop_when_disabled(self):
        from template_engine.storage.ltm_store import LTMStore, LTMConfig

        store = LTMStore(LTMConfig(enabled=False))
        result = store.store_correction("original", "corrected")
        assert result is None

    def test_query_corrections_empty_when_disabled(self):
        from template_engine.storage.ltm_store import LTMStore, LTMConfig

        store = LTMStore(LTMConfig(enabled=False))
        results = store.query_corrections("test query")
        assert results == []

    def test_hash_embed_produces_correct_dimension(self):
        from template_engine.storage.ltm_store import LTMStore

        embedding = LTMStore._hash_embed("test text")
        assert len(embedding) == 384
        assert all(isinstance(v, float) for v in embedding)
        assert all(-1.0 <= v <= 1.0 for v in embedding)

    def test_hash_embed_deterministic(self):
        from template_engine.storage.ltm_store import LTMStore

        e1 = LTMStore._hash_embed("hello world")
        e2 = LTMStore._hash_embed("hello world")
        assert e1 == e2

    def test_hash_embed_different_inputs(self):
        from template_engine.storage.ltm_store import LTMStore

        e1 = LTMStore._hash_embed("text a")
        e2 = LTMStore._hash_embed("text b")
        assert e1 != e2

    def test_config_from_env_disabled(self):
        from template_engine.storage.ltm_store import LTMConfig
        import os

        # Without QDRANT_URL, LTM should be disabled
        env_backup = os.environ.get("QDRANT_URL")
        os.environ.pop("QDRANT_URL", None)
        config = LTMConfig.from_env()
        assert not config.enabled
        if env_backup:
            os.environ["QDRANT_URL"] = env_backup

    def test_store_style_noop(self):
        from template_engine.storage.ltm_store import LTMStore, LTMConfig

        store = LTMStore(LTMConfig(enabled=False))
        assert store.store_style("The {indicator} increased from...", domain="plfs") is None

    def test_store_binding_noop(self):
        from template_engine.storage.ltm_store import LTMStore, LTMConfig

        store = LTMStore(LTMConfig(enabled=False))
        assert store.store_binding("LFPR", "labour_force_participation_rate") is None


class TestScribeLTMIntegration:
    """Step 27: Scribe LTM integration."""

    def test_scribe_has_ltm_methods(self):
        from agents.scribe_agent import ScribeAgent

        scribe = ScribeAgent()
        assert hasattr(scribe, "_get_ltm")
        assert hasattr(scribe, "_query_ltm_context")
        assert hasattr(scribe, "store_correction")

    def test_scribe_query_ltm_graceful_when_unavailable(self):
        from agents.scribe_agent import ScribeAgent

        scribe = ScribeAgent()
        # Should return empty dict when LTM is unavailable
        ctx = scribe._query_ltm_context("findings", {"row_count": 100})
        assert ctx == {}

    def test_scribe_store_correction_noop(self):
        from agents.scribe_agent import ScribeAgent

        scribe = ScribeAgent()
        # Should not raise
        scribe.store_correction("original text", "corrected text", "context")


class TestPLFSStyleRules:
    """Step 28: PLFS style rules engine."""

    def test_load_rules(self):
        from template_engine.inference.plfs_style_engine import _load_rules

        rules = _load_rules()
        assert "precision_rules" in rules
        assert "sentence_patterns" in rules
        assert "comparison_templates" in rules

    def test_format_value_percentage(self):
        from template_engine.inference.plfs_style_engine import format_value

        assert format_value(57.3, "percentage") == "57.3%"

    def test_format_value_count(self):
        from template_engine.inference.plfs_style_engine import format_value

        assert format_value(101579, "count") == "101,579"

    def test_format_value_ratio(self):
        from template_engine.inference.plfs_style_engine import format_value

        assert format_value(0.47, "ratio") == "0.47"

    def test_select_pattern_trend_increase(self):
        from template_engine.inference.plfs_style_engine import select_pattern

        pattern = select_pattern("trend_increase", {
            "indicator": "LFPR",
            "prev_value": "55.2%",
            "curr_value": "57.3%",
            "prev_period": "Q1 2024",
            "curr_period": "Q2 2024",
            "change": "2.1",
        })
        assert "LFPR" in pattern
        assert len(pattern) > 20

    def test_select_pattern_empty_for_unknown(self):
        from template_engine.inference.plfs_style_engine import select_pattern

        assert select_pattern("nonexistent_type") == ""

    def test_comparison_template_rural_urban(self):
        from template_engine.inference.plfs_style_engine import get_comparison_template

        tmpl = get_comparison_template("rural_urban")
        assert "Rural" in tmpl.get("dimensions", [])
        assert "Urban" in tmpl.get("dimensions", [])
        assert "template" in tmpl

    def test_hedge_qualifier_small_change(self):
        from template_engine.inference.plfs_style_engine import get_hedge_qualifier

        hedge = get_hedge_qualifier(0.3)
        assert hedge != ""  # Should produce a hedge phrase

    def test_hedge_qualifier_large_change(self):
        from template_engine.inference.plfs_style_engine import get_hedge_qualifier

        hedge = get_hedge_qualifier(5.0)
        assert hedge == ""  # No hedging for significant change

    def test_resolve_terminology(self):
        from template_engine.inference.plfs_style_engine import resolve_terminology

        assert resolve_terminology("LFPR") == "Labour Force Participation Rate"
        assert resolve_terminology("WPR") == "Worker Population Ratio"
        assert resolve_terminology("unknown") == "unknown"

    def test_format_indian_number(self):
        from template_engine.inference.plfs_style_engine import format_indian_number

        assert "lakh" in format_indian_number(500000)
        assert "crore" in format_indian_number(15000000)

    def test_source_citation(self):
        from template_engine.inference.plfs_style_engine import get_source_citation

        citation = get_source_citation()
        assert "PLFS" in citation
        assert "MoSPI" in citation


class TestAdaptiveRetryBudget:
    """Step 29: Adaptive retry budget (already in consensus engine)."""

    def test_priority_retry_map_exists(self):
        from agents.consensus_engine import _PRIORITY_RETRY_MAP

        assert _PRIORITY_RETRY_MAP["high"] == 4
        assert _PRIORITY_RETRY_MAP["medium"] == 3
        assert _PRIORITY_RETRY_MAP["low"] == 2


# ============================================================================
# PHASE 5 TESTS — Dashboard and API
# ============================================================================


class TestProgressSSE:
    """Step 30: SSE progress endpoint."""

    def test_progress_event_to_sse(self):
        from api.report_builder_api.progress_sse import ProgressEvent

        event = ProgressEvent(stage="binding", pct=25, message="Resolving...")
        sse = event.to_sse()
        assert "event: progress\n" in sse
        assert '"stage": "binding"' in sse
        assert '"pct": 25' in sse

    def test_progress_bus_publish_and_history(self):
        from api.report_builder_api.progress_sse import ProgressBus, ProgressEvent

        bus = ProgressBus()
        bus.publish(999, ProgressEvent(stage="test", pct=50, message="half"))
        history = bus.get_history(999)
        assert len(history) == 1
        assert history[0].stage == "test"
        assert history[0].pct == 50

    def test_progress_bus_history_limit(self):
        from api.report_builder_api.progress_sse import ProgressBus, ProgressEvent

        bus = ProgressBus()
        for i in range(60):
            bus.publish(1, ProgressEvent(stage=f"s{i}", pct=i))
        history = bus.get_history(1)
        assert len(history) == 50  # Max history

    def test_progress_bus_cleanup(self):
        from api.report_builder_api.progress_sse import ProgressBus, ProgressEvent

        bus = ProgressBus()
        bus.publish(2, ProgressEvent(stage="x", pct=10))
        bus.cleanup(2)
        # Subscribers cleared, history kept
        history = bus.get_history(2)
        assert len(history) == 1
        assert history[0].stage == "x"
        assert history[0].pct == 10

    def test_complete_event_format(self):
        from api.report_builder_api.progress_sse import ProgressEvent

        event = ProgressEvent(event_type="complete", stage="done", pct=100, message="Done")
        sse = event.to_sse()
        assert "event: complete\n" in sse


class TestEntityBindingAPI:
    """Step 31: Entity binding API schemas and store."""

    def test_binding_out_schema(self):
        from api.report_builder_api.entity_binding_api import BindingOut

        b = BindingOut(
            entity_id="e1",
            entity_name="LFPR",
            column_name="labour_force_participation_rate",
            confidence=0.95,
            method="exact",
            auto_accepted=True,
            status="resolved",
        )
        assert b.entity_id == "e1"
        assert b.confidence == 0.95

    def test_binding_store(self):
        from api.report_builder_api.entity_binding_api import (
            BindingOut, store_bindings, _get_store, _binding_store,
        )

        # Clean up
        _binding_store.pop(9999, None)

        bindings = [
            BindingOut(entity_id="e1", entity_name="LFPR", status="pending", confidence=0.8),
            BindingOut(entity_id="e2", entity_name="UR", status="unresolved"),
        ]
        store_bindings(9999, bindings)
        store = _get_store(9999)
        assert "e1" in store
        assert "e2" in store
        assert store["e1"].entity_name == "LFPR"

        # Cleanup
        _binding_store.pop(9999, None)

    def test_binding_result_out(self):
        from api.report_builder_api.entity_binding_api import BindingResultOut, BindingOut

        result = BindingResultOut(
            job_id=1,
            total=3,
            resolved=1,
            pending=1,
            unresolved=1,
            bindings=[
                BindingOut(entity_id="e1", entity_name="A", status="resolved"),
                BindingOut(entity_id="e2", entity_name="B", status="pending"),
                BindingOut(entity_id="e3", entity_name="C", status="unresolved"),
            ],
        )
        assert result.total == 3


class TestDashboardComponents:
    """Steps 32-33: Verify component files exist and have expected structure."""

    def test_progress_stream_component_exists(self):
        from pathlib import Path
        comp = Path(__file__).parent.parent.parent / "dashboard" / "components" / "report-builder" / "ReportProgressStream.tsx"
        assert comp.exists()
        content = comp.read_text()
        assert "EventSource" in content
        assert "ReportProgressStream" in content

    def test_entity_binding_panel_exists(self):
        from pathlib import Path
        comp = Path(__file__).parent.parent.parent / "dashboard" / "components" / "report-builder" / "EntityBindingPanel.tsx"
        assert comp.exists()
        content = comp.read_text()
        assert "EntityBindingPanel" in content
        assert "Auto-Resolve" in content


class TestReportPreviewEndpoint:
    """Step 35: Report preview (HTML)."""

    def test_escape_html(self):
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "api"))
        from report_builder_api.routes import _escape_html

        assert _escape_html("<script>") == "&lt;script&gt;"
        assert _escape_html('a "b" c') == 'a &quot;b&quot; c'
        assert _escape_html("a & b") == "a &amp; b"

    def test_render_html_table(self):
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "api"))
        from report_builder_api.routes import _render_html_table

        html = _render_html_table({
            "headers": ["Col A", "Col B"],
            "rows": [["val1", "val2"]],
        })
        assert "<table>" in html
        assert "Col A" in html
        assert "val1" in html
