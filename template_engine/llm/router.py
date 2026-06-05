"""Multi-provider LLM router — per-role assignment with global fallback.

Each agent role (SCRIBE, INFERRER, VERIFIER, PLANNER, ENRICHER) can be
assigned a different LLM provider + model via env vars:

    {ROLE}_PROVIDER=groq|gemini|openai|anthropic
    {ROLE}_API_KEY=...
    {ROLE}_MODEL=...

If a role's env vars are missing or the provider is rate-limited, the
router falls back to DEFAULT_LLM_* env vars.

Rate limiting: {PROVIDER}_RPM env var controls max requests per minute.

Usage:
    from template_engine.llm.router import get_llm_router
    router = get_llm_router()
    text = router.generate("scribe", prompt)
    data = router.generate_json("inferrer", prompt, schema)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Supported provider names
PROVIDERS = ("groq", "gemini", "openai", "anthropic")

# Agent roles that can have independent LLM assignments
ROLES = ("scribe", "inferrer", "verifier", "planner", "enricher")


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    name: str
    api_key: str
    model: str
    rpm_limit: int = 60         # Requests per minute

    @property
    def is_valid(self) -> bool:
        return bool(self.name and self.api_key and self.model)


@dataclass
class RateLimiter:
    """Simple token-bucket rate limiter per provider."""
    rpm: int = 60
    _timestamps: list[float] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def acquire(self) -> bool:
        """Try to acquire a slot. Returns False if rate-limited."""
        with self._lock:
            now = time.time()
            # Remove timestamps older than 60s
            self._timestamps = [t for t in self._timestamps if now - t < 60.0]
            if len(self._timestamps) >= self.rpm:
                return False
            self._timestamps.append(now)
            return True

    def wait_time(self) -> float:
        """Seconds until next available slot."""
        with self._lock:
            if len(self._timestamps) < self.rpm:
                return 0.0
            oldest = min(self._timestamps)
            return max(0.0, 60.0 - (time.time() - oldest))


class LLMRouter:
    """Routes LLM requests to the appropriate provider based on role.

    Cascade:
      1. Role-specific provider ({ROLE}_PROVIDER, {ROLE}_API_KEY, {ROLE}_MODEL)
      2. Global default (DEFAULT_LLM_PROVIDER, DEFAULT_LLM_API_KEY, DEFAULT_LLM_MODEL)
      3. Raise error if nothing configured
    """

    def __init__(self):
        self._role_configs: dict[str, ProviderConfig] = {}
        self._default_config: ProviderConfig | None = None
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._load_from_env()

    def _load_from_env(self) -> None:
        """Load all role and provider configurations from environment."""
        # Load per-role configs
        for role in ROLES:
            prefix = role.upper()
            provider = os.getenv(f"{prefix}_PROVIDER", "").lower()
            api_key = os.getenv(f"{prefix}_API_KEY", "")
            model = os.getenv(f"{prefix}_MODEL", "")
            if provider and api_key:
                self._role_configs[role] = ProviderConfig(
                    name=provider, api_key=api_key, model=model,
                )

        # Load global default
        default_provider = os.getenv("DEFAULT_LLM_PROVIDER", "").lower()
        default_key = os.getenv("DEFAULT_LLM_API_KEY", "")
        default_model = os.getenv("DEFAULT_LLM_MODEL", "")
        if default_provider and default_key:
            self._default_config = ProviderConfig(
                name=default_provider, api_key=default_key, model=default_model,
            )

        # Load rate limiters per provider
        for provider in PROVIDERS:
            rpm = int(os.getenv(f"{provider.upper()}_RPM", "60"))
            self._rate_limiters[provider] = RateLimiter(rpm=rpm)

    def _resolve_config(self, role: str) -> ProviderConfig:
        """Resolve provider config for a role (with fallback to global)."""
        role = role.lower()

        # Try role-specific first
        cfg = self._role_configs.get(role)
        if cfg and cfg.is_valid:
            # Check rate limit
            limiter = self._rate_limiters.get(cfg.name)
            if limiter and limiter.acquire():
                return cfg
            # Rate-limited — fall to global
            logger.warning("Role '%s' rate-limited on %s, falling back to global", role, cfg.name)

        # Try global default
        if self._default_config and self._default_config.is_valid:
            limiter = self._rate_limiters.get(self._default_config.name)
            if limiter and limiter.acquire():
                return self._default_config
            # Even global is rate-limited — wait briefly and try once more
            wait = limiter.wait_time() if limiter else 0
            if wait > 0 and wait < 5.0:
                time.sleep(wait)
                if limiter and limiter.acquire():
                    return self._default_config

        # Nothing available
        if cfg and cfg.is_valid:
            # Force through the role config even if rate-limited (best effort)
            logger.warning("All providers rate-limited; forcing through for role '%s'", role)
            return cfg
        if self._default_config and self._default_config.is_valid:
            return self._default_config

        raise RuntimeError(
            f"No LLM provider configured for role '{role}'. "
            f"Set {role.upper()}_PROVIDER + {role.upper()}_API_KEY or DEFAULT_LLM_* env vars."
        )

    def generate(self, role: str, prompt: str, *, system: str = "", temperature: float | None = None) -> str:
        """Generate text completion for a given role.

        Args:
            role: Agent role (scribe, inferrer, verifier, planner, enricher)
            prompt: User/task prompt
            system: Optional system prompt
            temperature: Override default temperature

        Returns:
            Generated text string.
        """
        cfg = self._resolve_config(role)
        return _call_provider(cfg, prompt, system=system, temperature=temperature)

    def generate_json(
        self, role: str, prompt: str, json_schema: dict[str, Any] | None = None,
        *, system: str = "", temperature: float | None = None,
    ) -> dict[str, Any]:
        """Generate JSON-structured output for a given role.

        Args:
            role: Agent role
            prompt: Prompt requesting JSON output
            json_schema: Optional schema to enforce
            system: Optional system prompt
            temperature: Override temperature

        Returns:
            Parsed JSON dict.
        """
        cfg = self._resolve_config(role)
        return _call_provider_json(cfg, prompt, json_schema=json_schema, system=system, temperature=temperature)

    def is_configured(self, role: str) -> bool:
        """Check if a role (or global fallback) has valid LLM config."""
        try:
            self._resolve_config(role)
            return True
        except RuntimeError:
            return False

    @property
    def configured_roles(self) -> list[str]:
        """List roles that have explicit provider configuration."""
        return [r for r in ROLES if r in self._role_configs and self._role_configs[r].is_valid]


# ---------------------------------------------------------------------------
# Provider call implementations
# ---------------------------------------------------------------------------

def _call_provider(cfg: ProviderConfig, prompt: str, *, system: str = "", temperature: float | None = None) -> str:
    """Dispatch to the appropriate provider SDK."""
    if cfg.name == "gemini":
        return _call_gemini(cfg, prompt, system=system, temperature=temperature)
    elif cfg.name == "groq":
        return _call_openai_compatible(cfg, prompt, system=system, temperature=temperature, base_url="https://api.groq.com/openai/v1")
    elif cfg.name == "openai":
        return _call_openai_compatible(cfg, prompt, system=system, temperature=temperature, base_url="https://api.openai.com/v1")
    elif cfg.name == "anthropic":
        return _call_anthropic(cfg, prompt, system=system, temperature=temperature)
    else:
        raise ValueError(f"Unknown provider: {cfg.name}")


def _call_provider_json(
    cfg: ProviderConfig, prompt: str, json_schema: dict[str, Any] | None = None,
    *, system: str = "", temperature: float | None = None,
) -> dict[str, Any]:
    """Call provider with JSON output mode."""
    import json as json_mod

    if cfg.name == "gemini":
        text = _call_gemini(cfg, prompt, system=system, temperature=temperature, json_mode=True)
    elif cfg.name in ("groq", "openai"):
        base = "https://api.groq.com/openai/v1" if cfg.name == "groq" else "https://api.openai.com/v1"
        text = _call_openai_compatible(cfg, prompt, system=system, temperature=temperature, base_url=base, json_mode=True)
    elif cfg.name == "anthropic":
        text = _call_anthropic(cfg, prompt, system=system, temperature=temperature)
    else:
        raise ValueError(f"Unknown provider: {cfg.name}")

    # Parse JSON from response
    text = text.strip()
    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    return json_mod.loads(text)


# ---------------------------------------------------------------------------
# Individual provider implementations
# ---------------------------------------------------------------------------

def _call_gemini(cfg: ProviderConfig, prompt: str, *, system: str = "", temperature: float | None = None, json_mode: bool = False) -> str:
    """Call Google Gemini via google.genai SDK."""
    try:
        import google.genai as genai
    except ImportError:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=cfg.api_key)
        model = genai.GenerativeModel(cfg.model)
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        resp = model.generate_content(full_prompt)
        return resp.text or ""

    client = genai.Client(api_key=cfg.api_key)
    config: dict[str, Any] = {}
    if temperature is not None:
        config["temperature"] = temperature
    if json_mode:
        config["response_mime_type"] = "application/json"

    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    resp = client.models.generate_content(
        model=cfg.model,
        contents=full_prompt,
        config=config if config else None,
    )
    return resp.text or ""


def _call_openai_compatible(
    cfg: ProviderConfig, prompt: str, *, system: str = "",
    temperature: float | None = None, base_url: str = "",
    json_mode: bool = False,
) -> str:
    """Call OpenAI-compatible API (works for Groq, OpenAI, etc.)."""
    import httpx

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_anthropic(cfg: ProviderConfig, prompt: str, *, system: str = "", temperature: float | None = None) -> str:
    """Call Anthropic Claude API."""
    import httpx

    body: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = temperature

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Get or create the global LLM router."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def reset_llm_router() -> None:
    """Reset singleton (for tests)."""
    global _router
    _router = None
