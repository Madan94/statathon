"""Unified tracing abstraction for the template engine.

Dispatches to OTel/Phoenix/LangFuse if configured, otherwise no-ops.
"""
from __future__ import annotations

import functools
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

logger = logging.getLogger(__name__)


@dataclass
class TracingConfig:
    """Configuration for tracing backends."""
    otel_endpoint: str = ""
    phoenix_endpoint: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    service_name: str = "template-engine"
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "TracingConfig":
        return cls(
            otel_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            phoenix_endpoint=os.getenv("PHOENIX_COLLECTOR_ENDPOINT", ""),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            langfuse_host=os.getenv("LANGFUSE_HOST", ""),
            service_name=os.getenv("OTEL_SERVICE_NAME", "template-engine"),
            enabled=os.getenv("TRACING_ENABLED", "1") != "0",
        )


# Global config (lazily initialized)
_config: TracingConfig | None = None
_tracer: Any = None


def init_tracing(config: TracingConfig | None = None) -> None:
    """Initialize tracing backends. Call once at startup."""
    global _config, _tracer
    _config = config or TracingConfig.from_env()

    if not _config.enabled:
        logger.info("Tracing disabled")
        return

    # Try OpenTelemetry
    if _config.otel_endpoint:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=_config.otel_endpoint)
            provider = TracerProvider()
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer(_config.service_name)
            logger.info("OTel tracing initialized: %s", _config.otel_endpoint)
        except ImportError:
            logger.debug("OpenTelemetry not installed, skipping OTel tracing")
        except Exception as exc:
            logger.warning("OTel init failed: %s", exc)

    # Try Phoenix
    if _config.phoenix_endpoint:
        try:
            import phoenix.otel
            phoenix.otel.register(
                project_name=_config.service_name,
                endpoint=_config.phoenix_endpoint,
            )
            logger.info("Phoenix tracing initialized: %s", _config.phoenix_endpoint)
        except ImportError:
            logger.debug("Arize Phoenix not installed, skipping Phoenix tracing")
        except Exception as exc:
            logger.warning("Phoenix init failed: %s", exc)

    # Try LangFuse
    if _config.langfuse_public_key and _config.langfuse_secret_key:
        try:
            from langfuse import Langfuse
            _langfuse = Langfuse(
                public_key=_config.langfuse_public_key,
                secret_key=_config.langfuse_secret_key,
                host=_config.langfuse_host or "https://cloud.langfuse.com",
            )
            logger.info("LangFuse tracing initialized")
        except ImportError:
            logger.debug("LangFuse not installed, skipping")
        except Exception as exc:
            logger.warning("LangFuse init failed: %s", exc)


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that traces a named operation.

    Usage:
        with trace_span("vlm_extraction", {"pages": 10}) as span:
            result = do_work()
            span["output_pages"] = len(result)

    The span dict can be enriched with additional attributes during execution.
    """
    span_data: dict[str, Any] = {
        "name": name,
        "start_time": time.time(),
        **(attributes or {}),
    }

    otel_span = None
    if _tracer:
        try:
            from opentelemetry import trace
            otel_span = _tracer.start_span(name)
            if attributes:
                for k, v in attributes.items():
                    otel_span.set_attribute(k, str(v))
        except Exception:
            pass

    try:
        yield span_data
    except Exception as exc:
        span_data["error"] = str(exc)
        if otel_span:
            try:
                otel_span.set_attribute("error", True)
                otel_span.set_attribute("error.message", str(exc))
            except Exception:
                pass
        raise
    finally:
        span_data["duration_ms"] = (time.time() - span_data["start_time"]) * 1000
        if otel_span:
            try:
                otel_span.end()
            except Exception:
                pass
        logger.debug("TRACE %s: %.1fms", name, span_data["duration_ms"])
