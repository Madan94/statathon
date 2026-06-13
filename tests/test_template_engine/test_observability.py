"""Tests for the observability/tracing layer."""
from __future__ import annotations

import pytest

from template_engine.observability.tracing import (
    trace_span,
    init_tracing,
    TracingConfig,
)


class TestTracingConfig:
    def test_from_env_defaults(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        config = TracingConfig.from_env()
        assert config.enabled is True
        assert config.otel_endpoint == ""
        assert config.service_name == "template-engine"

    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("TRACING_ENABLED", "0")
        config = TracingConfig.from_env()
        assert config.enabled is False


class TestTraceSpan:
    def test_span_context_manager(self):
        with trace_span("test_op", {"key": "val"}) as span:
            span["result"] = 42

        assert span["name"] == "test_op"
        assert span["result"] == 42
        assert "duration_ms" in span
        assert span["duration_ms"] >= 0

    def test_span_captures_error(self):
        with pytest.raises(ValueError):
            with trace_span("failing_op") as span:
                raise ValueError("test error")

        assert "error" in span
        assert "test error" in span["error"]

    def test_init_tracing_no_crash(self):
        # Should not crash even without backends
        config = TracingConfig(enabled=False)
        init_tracing(config)
