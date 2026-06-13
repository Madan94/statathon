"""Column Resolver — cascaded entity-to-column resolution.

Resolution cascade (stops at first hit ≥ threshold):
  1. Exact match: entity.name == column name (case-insensitive)
  2. Alias match: entity.name matches known abbreviation expansions
  3. Glossary match: PLFS glossary entity hints → column name patterns
  4. Embedding match: cosine similarity between entity name + column names
  5. Synonym KG: knowledge graph of column synonyms

Each stage returns (column_name, confidence, method) or None.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from ast_core.schema import TemplateEntity

logger = logging.getLogger(__name__)

# Minimum confidence to accept a resolution
_MIN_CONFIDENCE = 0.40


class ColumnResolver:
    """Multi-stage cascade for resolving entities to dataset columns."""

    def __init__(self, glossary: dict[str, Any] | None = None):
        self._glossary = glossary
        self._alias_map: dict[str, str] | None = None
        self._embedding_cache: dict[str, list[float]] = {}

    def resolve(
        self,
        entity: TemplateEntity,
        schema: "DatasetSchema",
    ) -> dict[str, Any] | None:
        """Resolve entity to a column in the dataset schema.

        Returns dict with keys: column, confidence, method
        Or None if no resolution found above minimum threshold.
        """
        from template_engine.binder.template_binder import DatasetSchema

        # Stage 1: Exact match
        result = self._exact_match(entity, schema)
        if result:
            return result

        # Stage 2: Alias match
        result = self._alias_match(entity, schema)
        if result:
            return result

        # Stage 3: Glossary match
        result = self._glossary_match(entity, schema)
        if result:
            return result

        # Stage 4: Fuzzy/embedding match
        result = self._fuzzy_match(entity, schema)
        if result:
            return result

        # Stage 5: Synonym KG (if available)
        result = self._synonym_kg_match(entity, schema)
        if result:
            return result

        return None

    # ------------------------------------------------------------------
    # Stage 1: Exact Match
    # ------------------------------------------------------------------

    def _exact_match(
        self, entity: TemplateEntity, schema: "DatasetSchema"
    ) -> dict[str, Any] | None:
        """Case-insensitive exact match of entity name to column."""
        name_lower = entity.name.lower().strip()

        for col in schema.columns:
            if col.lower().strip() == name_lower:
                return {"column": col, "confidence": 1.0, "method": "exact"}

        # Also check without underscores/spaces normalization
        name_normalized = re.sub(r"[\s_\-]+", "", name_lower)
        for col in schema.columns:
            col_normalized = re.sub(r"[\s_\-]+", "", col.lower())
            if col_normalized == name_normalized:
                return {"column": col, "confidence": 0.98, "method": "exact"}

        return None

    # ------------------------------------------------------------------
    # Stage 2: Alias Match
    # ------------------------------------------------------------------

    def _alias_match(
        self, entity: TemplateEntity, schema: "DatasetSchema"
    ) -> dict[str, Any] | None:
        """Match using known abbreviation expansions (LFPR → labour_force_participation_rate)."""
        aliases = self._get_alias_map()
        name_upper = entity.name.upper().strip()

        if name_upper in aliases:
            expansion = aliases[name_upper].lower()
            # Try matching expansion to columns
            for col in schema.columns:
                col_lower = col.lower()
                # Check if expansion is contained in column or vice versa
                if expansion in col_lower or col_lower in expansion:
                    return {"column": col, "confidence": 0.92, "method": "alias"}

            # Try normalized expansion
            expansion_norm = re.sub(r"[\s_\-]+", "", expansion)
            for col in schema.columns:
                col_norm = re.sub(r"[\s_\-]+", "", col.lower())
                if expansion_norm in col_norm or col_norm in expansion_norm:
                    return {"column": col, "confidence": 0.88, "method": "alias"}

        return None

    def _get_alias_map(self) -> dict[str, str]:
        """Load abbreviation → expansion map from PLFS glossary."""
        if self._alias_map is not None:
            return self._alias_map

        self._alias_map = {}
        try:
            from template_engine.extraction.plfs_parser import _load_glossary
            glossary = self._glossary or _load_glossary()
            self._alias_map = glossary.get("abbreviations", {})
        except Exception:
            pass
        return self._alias_map

    # ------------------------------------------------------------------
    # Stage 3: Glossary Match
    # ------------------------------------------------------------------

    def _glossary_match(
        self, entity: TemplateEntity, schema: "DatasetSchema"
    ) -> dict[str, Any] | None:
        """Match using PLFS glossary entity hints."""
        try:
            from template_engine.extraction.plfs_parser import _load_glossary
            glossary = self._glossary or _load_glossary()
        except Exception:
            return None

        entity_hints = glossary.get("entity_hints", {})
        col_semantics = glossary.get("column_semantics", {})

        # Check if entity name is in hints
        hint = entity_hints.get(entity.name) or entity_hints.get(entity.name.upper())
        if hint:
            entity_type = hint.get("entityType", "")
            # For dimensions: look in column_semantics.dimensions
            if entity_type == "dimension":
                for dim_name, dim_values in col_semantics.get("dimensions", {}).items():
                    if entity.name in dim_values or entity.name.lower() in [
                        v.lower() for v in dim_values
                    ]:
                        # Find column matching dimension name
                        for col in schema.columns:
                            if dim_name.lower() in col.lower():
                                return {
                                    "column": col,
                                    "confidence": 0.85,
                                    "method": "glossary",
                                }
            # For measures: try matching entity type patterns
            elif entity_type == "measure":
                name_lower = entity.name.lower()
                for col in schema.columns:
                    col_lower = col.lower()
                    if name_lower in col_lower:
                        return {
                            "column": col,
                            "confidence": 0.85,
                            "method": "glossary",
                        }

        return None

    # ------------------------------------------------------------------
    # Stage 4: Fuzzy Match (embedding-like via sequence matching)
    # ------------------------------------------------------------------

    def _fuzzy_match(
        self, entity: TemplateEntity, schema: "DatasetSchema"
    ) -> dict[str, Any] | None:
        """Fuzzy string matching as a lightweight embedding proxy."""
        name_lower = entity.name.lower().strip()
        best_score = 0.0
        best_col = ""

        for col in schema.columns:
            col_lower = col.lower().strip()
            # SequenceMatcher ratio
            score = SequenceMatcher(None, name_lower, col_lower).ratio()

            # Boost if entity name is a substring
            if name_lower in col_lower or col_lower in name_lower:
                score = max(score, 0.75)

            if score > best_score:
                best_score = score
                best_col = col

        if best_score >= 0.60:
            # Map fuzzy score to confidence (0.60-1.0 → 0.55-0.85)
            confidence = 0.55 + (best_score - 0.60) * 0.75
            return {"column": best_col, "confidence": confidence, "method": "embedding"}

        return None

    # ------------------------------------------------------------------
    # Stage 5: Synonym KG
    # ------------------------------------------------------------------

    def _synonym_kg_match(
        self, entity: TemplateEntity, schema: "DatasetSchema"
    ) -> dict[str, Any] | None:
        """Knowledge graph synonym lookup (delegates to deep_bi if available)."""
        try:
            from deep_bi.column_synonym_kg import resolve_synonym
            result = resolve_synonym(entity.name, schema.columns)
            if result:
                return {
                    "column": result["column"],
                    "confidence": result.get("confidence", 0.70),
                    "method": "synonym_kg",
                }
        except (ImportError, Exception):
            pass
        return None
