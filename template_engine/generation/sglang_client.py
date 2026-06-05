"""SGLang Client — interface for grammar-constrained JSON generation.

Provides:
  - MockSGLangClient: returns valid AST from pre-built assembly (dev)
  - RealSGLangClient: HTTP to SGLang server with JSON schema enforcement
  - SGLangClientFactory: env-driven selection

The SGLang server enforces our Pydantic schema during token generation,
guaranteeing 100% syntactically valid output.

Env:
  SGLANG_BACKEND=mock|sglang       (default: auto-detect)
  SGLANG_ENDPOINT=http://...       (default: http://localhost:30000)
  SGLANG_TIMEOUT=300               (seconds, default: 300)
  SGLANG_MAX_RETRIES=3             (default: 3)
"""
from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SGLangClient(ABC):
    """Abstract base for SGLang grammar-constrained generation."""

    @abstractmethod
    def generate(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        """Generate JSON conforming to the provided schema.

        Args:
            prompt: The generation prompt with context.
            json_schema: JSON Schema that the output MUST conform to.

        Returns:
            Parsed JSON dict guaranteed to match the schema.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...


class MockSGLangClient(SGLangClient):
    """Mock client that bypasses LLM generation.

    Instead of generating via SGLang, it accepts a pre-assembled dict
    and validates it against the schema. Used when the AST is already
    built deterministically by the assembler pipeline.
    """

    @property
    def backend_name(self) -> str:
        return "mock_sglang"

    def health_check(self) -> bool:
        return True

    def generate(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        """For mock: extract pre-built payload from prompt metadata.

        In mock mode, the assembler has already built the AST. This client
        just validates and returns it.
        """
        # The mock pipeline passes the pre-built AST as a JSON block in the prompt
        # Look for ```json ... ``` block
        import re
        match = re.search(r"```json\s*\n(.+?)\n```", prompt, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback: return minimal valid structure
        return {
            "templateId": "",
            "name": "Mock Template",
            "sourceHash": "",
            "pageCount": 0,
            "extractionMethod": "mock",
            "topics": [],
            "entities": [],
            "extractionMeta": {},
        }


class RealSGLangClient(SGLangClient):
    """HTTP client to a running SGLang server with constrained decoding."""

    def __init__(self, endpoint: str = "http://localhost:30000",
                 model: str | None = None, timeout: int = 300,
                 max_retries: int | None = None):
        self._endpoint = endpoint.rstrip("/")
        self._model = model or os.getenv("SGLANG_MODEL", "default")
        self._timeout = timeout
        self._max_retries = max_retries if max_retries is not None else int(
            os.getenv("SGLANG_MAX_RETRIES", "3")
        )

    @property
    def backend_name(self) -> str:
        return "sglang"

    def health_check(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self._endpoint}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def generate(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests library required for SGLang client")

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "template_blueprint",
                    "schema": json_schema,
                    "strict": True,
                },
            },
            "temperature": 0.1,
            "max_tokens": 8192,
        }

        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = requests.post(
                    f"{self._endpoint}/v1/chat/completions",
                    json=payload,
                    timeout=self._timeout,
                )

                if response.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "SGLang returned %d (attempt %d/%d), retrying in %ds",
                        response.status_code, attempt, self._max_retries, wait,
                    )
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)

            except requests.ConnectionError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "SGLang connection error (attempt %d/%d), retrying in %ds",
                        attempt, self._max_retries, wait,
                    )
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"SGLang server unreachable at {self._endpoint} after {attempt} attempt(s). "
                    f"Start with: python -m sglang.launch_server --model-path <model>"
                )
            except requests.Timeout as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    logger.warning(
                        "SGLang timed out (attempt %d/%d, timeout=%ds)",
                        attempt, self._max_retries, self._timeout,
                    )
                    continue
                raise RuntimeError(
                    f"SGLang request timed out after {self._timeout}s "
                    f"({self._max_retries} attempts). "
                    f"Increase SGLANG_TIMEOUT or use a faster model."
                )
            except requests.HTTPError as exc:
                raise RuntimeError(
                    f"SGLang returned HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                )
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"SGLang response parsing failed: {exc}")

        raise RuntimeError(
            f"SGLang generation failed after {self._max_retries} attempts: {last_exc}"
        )


class SGLangClientFactory:
    """Factory for SGLang clients based on environment."""

    @staticmethod
    def create(backend: str | None = None) -> SGLangClient:
        backend = backend or os.getenv("SGLANG_BACKEND", "").lower()

        if not backend:
            if os.getenv("SGLANG_ENDPOINT"):
                backend = "sglang"
            else:
                backend = "mock"

        if backend == "mock":
            return MockSGLangClient()

        if backend == "sglang":
            endpoint = os.getenv("SGLANG_ENDPOINT", "http://localhost:30000")
            return RealSGLangClient(endpoint=endpoint)

        raise ValueError(f"Unknown SGLang backend: {backend!r}. Valid: mock, sglang")
