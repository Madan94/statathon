"""
STEP 2 — Static Domain Loading.

Loads the curated, versioned domain packs from ``domain_registry/<usecase>.json``
and exposes them as :class:`Domain` records. These are the grounded "source of
truth" domains for each usecase (~15 each).
"""
from __future__ import annotations

import functools
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from semantic_mapping_v2.config import DOMAIN_REGISTRY_DIR, USECASES

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class Domain:
    domain_id: str
    domain_name: str
    domain_type: str  # 'static' | 'dynamic'
    description: str
    usecase: str = ""
    synonyms: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def embed_text(self) -> str:
        """Grounded document text for embedding this domain."""
        parts = [self.domain_name.replace("_", " ")]
        if self.description:
            parts.append(self.description)
        if self.synonyms:
            parts.append("synonyms: " + ", ".join(self.synonyms[:12]))
        if self.examples:
            parts.append("examples: " + ", ".join(str(e) for e in self.examples[:12]))
        return ". ".join(parts)

    def keyword_tokens(self) -> set[str]:
        toks: set[str] = set()
        toks |= set(_TOKEN_RE.findall(self.domain_name.lower()))
        for s in self.synonyms:
            toks |= set(_TOKEN_RE.findall(s.lower()))
        for e in self.examples:
            toks |= set(_TOKEN_RE.findall(str(e).lower()))
        return toks

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "domain_name": self.domain_name,
            "domain_type": self.domain_type,
            "description": self.description,
            "usecase": self.usecase,
            "synonyms": self.synonyms,
            "examples": self.examples,
            "confidence": self.confidence,
        }


class DomainRegistryLoader:
    """Reads and caches the static domain packs."""

    @functools.lru_cache(maxsize=None)
    def _load_raw(self, usecase: str) -> dict[str, Any]:
        path = DOMAIN_REGISTRY_DIR / f"{usecase}.json"
        if not path.exists():
            logger.warning("Domain pack missing for usecase '%s' (%s)", usecase, path)
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to parse domain pack %s: %s", path, exc)
            return {}

    def usecase_description(self, usecase: str) -> str:
        raw = self._load_raw(usecase)
        desc = raw.get("description", "")
        kws = ", ".join(raw.get("keywords", [])[:20])
        return f"{usecase}. {desc}. keywords: {kws}".strip()

    def keyword_tokens(self, usecase: str) -> set[str]:
        raw = self._load_raw(usecase)
        toks: set[str] = set()
        for kw in raw.get("keywords", []):
            toks |= set(_TOKEN_RE.findall(str(kw).lower()))
        for d in raw.get("domains", []):
            toks |= set(_TOKEN_RE.findall(str(d.get("domain", "")).lower()))
            for s in d.get("synonyms", []):
                toks |= set(_TOKEN_RE.findall(str(s).lower()))
        return toks

    def load_domains(self, usecase: str) -> list[Domain]:
        raw = self._load_raw(usecase)
        domains: list[Domain] = []
        for d in raw.get("domains", []):
            name = str(d.get("domain", "")).strip()
            if not name:
                continue
            domains.append(
                Domain(
                    domain_id=f"static::{usecase}::{name}",
                    domain_name=name,
                    domain_type="static",
                    description=str(d.get("description", "")).strip(),
                    usecase=usecase,
                    synonyms=[str(s) for s in d.get("synonyms", [])],
                    examples=[str(e) for e in d.get("examples", [])],
                    confidence=1.0,
                )
            )
        return domains

    def available_usecases(self) -> list[str]:
        return [uc for uc in USECASES if (DOMAIN_REGISTRY_DIR / f"{uc}.json").exists()]
