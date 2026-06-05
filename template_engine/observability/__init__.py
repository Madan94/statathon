"""Observability sub-package for the template engine pipeline.

Provides structured tracing via:
  - OpenTelemetry (structured spans)
  - Arize Phoenix (LLM observability)
  - LangFuse (prompt/completion tracking)

All three backends are optional — graceful no-op if not configured.
"""
from template_engine.observability.tracing import (
    trace_span,
    init_tracing,
    TracingConfig,
)
