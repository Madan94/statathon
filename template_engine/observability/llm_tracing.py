"""LLM-specific tracing for prompt/completion observability.

Wraps LLM calls with structured metadata (model, tokens, latency, role)
and dispatches to Langfuse generations + OTel spans.
"""
from __future__ import annotations

import functools
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Generator

from template_engine.observability.tracing import trace_span

logger = logging.getLogger(__name__)

# Langfuse client (initialized lazily)
_langfuse: Any = None


def _get_langfuse() -> Any:
    """Get Langfuse client if available."""
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    try:
        import os
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        if pk and sk:
            from langfuse import Langfuse
            _langfuse = Langfuse(
                public_key=pk,
                secret_key=sk,
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
        else:
            _langfuse = False  # Disabled sentinel
    except ImportError:
        _langfuse = False
    except Exception as exc:
        logger.debug("Langfuse init failed: %s", exc)
        _langfuse = False
    return _langfuse


@dataclass
class LLMSpanResult:
    """Result of a traced LLM call."""
    output: str = ""
    model: str = ""
    role: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False
    error: str | None = None


@contextmanager
def llm_span(
    role: str,
    model: str = "",
    prompt: str = "",
    metadata: dict[str, Any] | None = None,
) -> Generator[LLMSpanResult, None, None]:
    """Trace an LLM call with Langfuse generation + OTel span.

    Usage:
        with llm_span("scribe", model="gemini-2.0-flash", prompt=p) as result:
            result.output = call_llm(p)
            result.prompt_tokens = 100
            result.completion_tokens = 50
    """
    result = LLMSpanResult(model=model, role=role)
    start = time.time()

    attrs = {"llm.role": role, "llm.model": model, **(metadata or {})}

    with trace_span(f"llm.{role}", attrs):
        try:
            yield result
        except Exception as exc:
            result.error = str(exc)
            raise
        finally:
            result.latency_ms = (time.time() - start) * 1000
            result.total_tokens = result.prompt_tokens + result.completion_tokens

            # Log to Langfuse if available
            lf = _get_langfuse()
            if lf and lf is not False:
                try:
                    lf.generation(
                        name=f"{role}_generation",
                        model=model,
                        input=prompt[:2000] if prompt else "",
                        output=result.output[:2000] if result.output else "",
                        metadata={
                            "role": role,
                            "cached": result.cached,
                            **(metadata or {}),
                        },
                        usage={
                            "input": result.prompt_tokens,
                            "output": result.completion_tokens,
                            "total": result.total_tokens,
                        },
                    )
                except Exception as exc:
                    logger.debug("Langfuse generation log failed: %s", exc)

            logger.debug(
                "LLM %s [%s]: %d tokens, %.0fms",
                role, model, result.total_tokens, result.latency_ms,
            )


def trace_llm_call(role: str, model: str = ""):
    """Decorator to trace an LLM function call.

    The decorated function should return a string (the LLM output).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            prompt = kwargs.get("prompt", "") or (args[0] if args else "")
            with llm_span(role, model=model, prompt=str(prompt)[:500]) as result:
                output = func(*args, **kwargs)
                if isinstance(output, str):
                    result.output = output
                return output
        return wrapper
    return decorator
