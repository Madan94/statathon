"""
STEP 5c — Canonical column identity.

After the normalization layer (``ColumnPreprocessorV2`` abbreviation expansion +
the LLM ``column_enricher``) has corrected/expanded every column header, this
module turns the corrected phrase into a single, stable identity used by the
WHOLE pipeline and persisted for the UI:

  * ``canonical_name`` — unique ``snake_case`` key (the real identity flowing
    through semantic mapping, clustering, KG, schema, validation, z-score, IQR,
    missing-value and persistence).
  * ``display_name``   — tidy Title Case label shown to the user.
  * ``full_phrase``    — the verbose corrected phrase (used for embeddings).
  * ``original_name``  — the raw header, kept for provenance/audit.

Pure and deterministic so the ``--no-llm`` path is fully reproducible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:  # avoid a runtime import cycle with feature_extraction
    from semantic_mapping_v2.feature_extraction import ColumnFeature

_WORD_RE = re.compile(r"[a-z0-9]+")
# Cap canonical length so keys stay sane without losing meaning.
_MAX_WORDS = 8


@dataclass
class NameRecord:
    original_name: str
    canonical_name: str
    display_name: str
    full_phrase: str

    def to_dict(self) -> dict[str, str]:
        return {
            "original_name": self.original_name,
            "canonical_name": self.canonical_name,
            # alias so existing persistence readers that look for
            # ``normalized_name`` keep working.
            "normalized_name": self.canonical_name,
            "display_name": self.display_name,
            "full_phrase": self.full_phrase,
        }


def _words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def _snake(phrase: str, fallback: str) -> str:
    words = _words(phrase) or _words(fallback)
    if len(words) > _MAX_WORDS:
        words = words[:_MAX_WORDS]
    return "_".join(words) or "column"


def _title(phrase: str, fallback: str) -> str:
    words = _words(phrase) or _words(fallback)
    if not words:
        return str(fallback) or "Column"
    if len(words) > _MAX_WORDS:
        words = words[:_MAX_WORDS]
    return " ".join(w.capitalize() for w in words)


def canonicalize_features(
    features: "Mapping[str, ColumnFeature]",
) -> dict[str, NameRecord]:
    """Build a raw-name -> :class:`NameRecord` map (insertion order preserved).

    ``feat.normalized`` is the corrected phrase produced by the normalization
    layer; the raw key is the fallback when that phrase is empty. Canonical
    collisions are de-duplicated with a numeric suffix so identity stays 1:1.
    """
    records: dict[str, NameRecord] = {}
    seen: dict[str, int] = {}
    for raw, feat in features.items():
        raw_s = str(raw)
        phrase = (getattr(feat, "normalized", "") or "").strip() or raw_s
        base = _snake(phrase, raw_s)
        if base in seen:
            seen[base] += 1
            canonical = f"{base}_{seen[base]}"
        else:
            seen[base] = 1
            canonical = base
        records[raw_s] = NameRecord(
            original_name=raw_s,
            canonical_name=canonical,
            display_name=_title(phrase, raw_s),
            full_phrase=phrase,
        )
    return records
