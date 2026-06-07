"""Google Gen AI SDK client (google-genai). Replaces deprecated google.generativeai."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.5-flash"
_client: Any | None = None
_client_init_attempted = False


def default_model_name() -> str:
    return os.getenv("GEMINI_SEMANTIC_MODEL", _DEFAULT_MODEL)


def get_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None


def get_gemini_client() -> Any | None:
    """Return a cached ``google.genai.Client`` or None if unavailable."""
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True

    api_key = get_api_key()
    if not api_key:
        return None

    try:
        from google import genai
    except ImportError:
        logger.debug("google-genai package not installed")
        return None

    try:
        _client = genai.Client(api_key=api_key)
    except Exception as exc:
        logger.warning("Gemini client init failed: %s", exc)
        _client = None
    return _client


@dataclass
class GenerateContentResponse:
    text: str


class GenerativeModel:
    """Drop-in replacement for ``google.generativeai.GenerativeModel``."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or default_model_name()
        self._client = get_gemini_client()

    def generate_content(
        self,
        contents: str,
        *,
        system_instruction: str | None = None,
        **config: Any,
    ) -> GenerateContentResponse:
        if self._client is None:
            raise RuntimeError("Gemini client is not configured")
        kwargs: dict[str, Any] = {"model": self.model_name, "contents": contents}
        if system_instruction or config:
            from google.genai import types

            cfg_kwargs = dict(config)
            if system_instruction:
                cfg_kwargs["system_instruction"] = system_instruction
            kwargs["config"] = types.GenerateContentConfig(**cfg_kwargs)
        response = self._client.models.generate_content(**kwargs)
        text = getattr(response, "text", None) or ""
        return GenerateContentResponse(text=text.strip())


def get_generative_model(model_name: str | None = None) -> GenerativeModel | None:
    if get_gemini_client() is None:
        return None
    return GenerativeModel(model_name=model_name)


def generate_text(
    prompt: str,
    *,
    model_name: str | None = None,
    system_instruction: str | None = None,
    **config: Any,
) -> str | None:
    model = get_generative_model(model_name)
    if model is None:
        return None
    try:
        return model.generate_content(
            prompt,
            system_instruction=system_instruction,
            **config,
        ).text
    except Exception as exc:
        logger.warning("Gemini generate_text failed: %s", exc)
        return None
