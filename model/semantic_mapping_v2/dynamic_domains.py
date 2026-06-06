"""
STEP 3 — Dynamic Domain Generation (LLM).

Asks Gemini to propose *additional* grounded domains that the curated static
pack does not already cover, given the dataset name, usecase, static domains,
column names and sample values.

Guardrails enforced both in the prompt and in post-processing:
  * grounded (derived from the supplied columns/values);
  * each domain must plausibly cover multiple columns;
  * no duplicates of static domains (by normalized name / synonym);
  * at most ``max_domains`` (default 15).

Returns a list of :class:`Domain` (domain_type='dynamic'); empty list when the
LLM is unavailable so the pipeline degrades to static-only cleanly.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from semantic_mapping_v2.domain_loader import Domain

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _strip_fence(text: str) -> str:
    s = text.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _norm(name: str) -> str:
    return "_".join(_TOKEN_RE.findall(str(name).lower()))


class DynamicDomainGenerator:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")

    def generate(
        self,
        *,
        usecase: str,
        dataset_name: str,
        static_domains: list[Domain],
        column_names: list[str],
        sample_values: dict[str, list[Any]] | None = None,
        max_domains: int = 15,
    ) -> list[Domain]:
        key = _gemini_key()
        if not key:
            logger.info("No Gemini key; skipping dynamic domain generation.")
            return []
        try:
            import google.generativeai as genai
        except ImportError:
            logger.warning("google.generativeai not installed; skipping dynamic domains.")
            return []

        static_names = {_norm(d.domain_name) for d in static_domains}
        static_syn = set()
        for d in static_domains:
            for s in d.synonyms:
                static_syn.add(_norm(s))

        prompt = self._build_prompt(
            usecase=usecase,
            dataset_name=dataset_name,
            static_domains=static_domains,
            column_names=column_names,
            sample_values=sample_values or {},
            max_domains=max_domains,
        )

        genai.configure(api_key=key)
        model = genai.GenerativeModel(self.model_name)
        timeout = int(os.getenv("GEMINI_REQUEST_TIMEOUT_SEC", "90"))

        parsed: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                resp = model.generate_content(prompt, request_options={"timeout": timeout})
                raw = (resp.text or "").strip()
                if not raw:
                    return []
                loaded = json.loads(_strip_fence(raw))
                if isinstance(loaded, dict):
                    parsed = loaded
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if any(k in msg for k in ("429", "rate", "quota", "exhausted")) and attempt < 2:
                    time.sleep(5 * (2 ** attempt))
                    continue
                logger.warning("Dynamic domain generation failed: %s", exc)
                return []

        if not isinstance(parsed, dict):
            return []

        return self._parse_domains(
            parsed.get("domains"), usecase, static_names, static_syn, max_domains
        )

    # -- internals -----------------------------------------------------------
    def _build_prompt(
        self,
        *,
        usecase: str,
        dataset_name: str,
        static_domains: list[Domain],
        column_names: list[str],
        sample_values: dict[str, list[Any]],
        max_domains: int,
    ) -> str:
        samples_compact = {
            c: [str(v)[:30] for v in (sample_values.get(c, []) or [])[:4]]
            for c in column_names
        }
        payload = {
            "dataset_name": dataset_name,
            "usecase": usecase,
            "static_domains": [d.domain_name for d in static_domains],
            "column_names": column_names,
            "sample_values": samples_compact,
        }
        return f"""
You are a grounded Data Domain Designer for official statistics.

INPUT:
{json.dumps(payload, ensure_ascii=True)}

TASK:
Propose ADDITIONAL semantic domains that are NOT already represented by the
supplied static_domains, to better cover the dataset's columns.

HARD RULES:
1. GROUNDED: every domain must be derivable from the given column names / sample values.
2. MULTI-COLUMN: each domain should plausibly group two or more columns. Do not invent a domain for a single niche column.
3. NO DUPLICATES: do not restate any static_domain or an obvious synonym of one.
4. LIMIT: return at most {max_domains} domains. Fewer is better than forced.
5. NAMING: domain_name must be a short snake_case concept (e.g. "renewable_energy", "price_index").

OUTPUT — valid JSON ONLY, no markdown:
{{
  "domains": [
    {{"domain_name": "string_snake_case", "description": "<=15 words grounded in the columns", "confidence": 0.0}}
  ]
}}
"""

    def _parse_domains(
        self,
        domains: Any,
        usecase: str,
        static_names: set[str],
        static_syn: set[str],
        max_domains: int,
    ) -> list[Domain]:
        if not isinstance(domains, list):
            return []
        out: list[Domain] = []
        seen: set[str] = set()
        for entry in domains:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("domain_name") or "").strip()
            if not name:
                continue
            norm = _norm(name)
            if not norm or norm in static_names or norm in static_syn or norm in seen:
                continue
            seen.add(norm)
            try:
                conf = float(entry.get("confidence", 0.7))
            except (TypeError, ValueError):
                conf = 0.7
            out.append(
                Domain(
                    domain_id=f"dynamic::{usecase}::{norm}",
                    domain_name=norm,
                    domain_type="dynamic",
                    description=str(entry.get("description", "")).strip(),
                    usecase=usecase,
                    synonyms=[],
                    examples=[],
                    confidence=max(0.0, min(1.0, conf)),
                )
            )
            if len(out) >= max_domains:
                break
        return out
