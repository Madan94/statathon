"""Template Binder — binds extracted template entities to dataset columns.

This module is the bridge between Phase 2 (extraction) and Phase 3 (generation).
It takes a template (list of TopicNodes with entities) and a dataset schema,
then resolves each entity to a concrete column via the ColumnResolver cascade.

Auto-accept threshold: entities with confidence >= 0.90 are automatically bound.
Lower-confidence entities are flagged for user review via the dashboard UI.

Binding lifecycle:
  1. Extract entities from template (Phase 2 output)
  2. Load dataset schema (column names, types, sample values)
  3. Resolve entity → column via cascade (exact → alias → glossary → embedding)
  4. Auto-accept high-confidence bindings
  5. Return binding map + pending list for UI approval
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ast_core.schema import TemplateEntity, TopicNode, QuestionNode

logger = logging.getLogger(__name__)

# Confidence threshold for auto-accepting bindings
AUTO_ACCEPT_THRESHOLD = 0.90


@dataclass
class ColumnBinding:
    """A resolved binding from entity to dataset column."""
    entityId: str
    entityName: str
    columnName: str
    confidence: float
    method: str  # exact | alias | glossary | embedding | synonym_kg | manual
    autoAccepted: bool = False
    userOverride: str | None = None  # user can override columnName

    @property
    def effective_column(self) -> str:
        return self.userOverride or self.columnName

    def to_dict(self) -> dict[str, Any]:
        out = {
            "entityId": self.entityId,
            "entityName": self.entityName,
            "columnName": self.columnName,
            "confidence": self.confidence,
            "method": self.method,
            "autoAccepted": self.autoAccepted,
        }
        if self.userOverride:
            out["userOverride"] = self.userOverride
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnBinding":
        return cls(
            entityId=str(d.get("entityId", "")),
            entityName=str(d.get("entityName", "")),
            columnName=str(d.get("columnName", "")),
            confidence=float(d.get("confidence", 0)),
            method=str(d.get("method", "manual")),
            autoAccepted=bool(d.get("autoAccepted", False)),
            userOverride=d.get("userOverride"),
        )


@dataclass
class BindingResult:
    """Result of template binding operation."""
    templateId: str
    datasetId: str
    bindings: list[ColumnBinding] = field(default_factory=list)
    pending: list[ColumnBinding] = field(default_factory=list)  # needs user review
    unresolved: list[str] = field(default_factory=list)  # entity IDs with no match

    @property
    def is_complete(self) -> bool:
        """All entities resolved (no pending or unresolved)."""
        return len(self.pending) == 0 and len(self.unresolved) == 0

    @property
    def auto_accepted_count(self) -> int:
        return sum(1 for b in self.bindings if b.autoAccepted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "templateId": self.templateId,
            "datasetId": self.datasetId,
            "bindings": [b.to_dict() for b in self.bindings],
            "pending": [b.to_dict() for b in self.pending],
            "unresolved": self.unresolved,
            "isComplete": self.is_complete,
            "autoAcceptedCount": self.auto_accepted_count,
        }


@dataclass
class DatasetSchema:
    """Minimal dataset schema for binding resolution."""
    datasetId: str
    columns: list[str]
    columnTypes: dict[str, str] = field(default_factory=dict)  # col → type
    sampleValues: dict[str, list[str]] = field(default_factory=dict)  # col → samples
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dataframe(cls, dataset_id: str, df: Any) -> "DatasetSchema":
        """Build schema from a pandas DataFrame."""
        columns = list(df.columns)
        col_types = {col: str(df[col].dtype) for col in columns}
        samples = {}
        for col in columns:
            unique = df[col].dropna().unique()[:5]
            samples[col] = [str(v) for v in unique]
        return cls(
            datasetId=dataset_id,
            columns=columns,
            columnTypes=col_types,
            sampleValues=samples,
        )


class TemplateBinder:
    """Binds template entities to dataset columns using the resolver cascade."""

    def __init__(self, resolver=None):
        from template_engine.binder.column_resolver import ColumnResolver
        self._resolver = resolver or ColumnResolver()

    def bind(
        self,
        topics: list[TopicNode],
        entities: list[TemplateEntity],
        schema: DatasetSchema,
        *,
        template_id: str = "default",
    ) -> BindingResult:
        """Resolve all template entities against the dataset schema.

        Returns BindingResult with auto-accepted, pending, and unresolved lists.
        """
        result = BindingResult(
            templateId=template_id,
            datasetId=schema.datasetId,
        )

        # Collect unique entities
        seen_ids: set[str] = set()
        unique_entities: list[TemplateEntity] = []
        for ent in entities:
            if ent.entityId not in seen_ids:
                seen_ids.add(ent.entityId)
                unique_entities.append(ent)

        # Resolve each entity
        for entity in unique_entities:
            resolution = self._resolver.resolve(entity, schema)

            if resolution is None:
                result.unresolved.append(entity.entityId)
                logger.debug("Unresolved entity: %s (%s)", entity.name, entity.entityId)
                continue

            binding = ColumnBinding(
                entityId=entity.entityId,
                entityName=entity.name,
                columnName=resolution["column"],
                confidence=resolution["confidence"],
                method=resolution["method"],
            )

            # Auto-accept if high confidence
            if binding.confidence >= AUTO_ACCEPT_THRESHOLD:
                binding.autoAccepted = True
                result.bindings.append(binding)
                logger.debug(
                    "Auto-accepted: %s → %s (%.2f, %s)",
                    entity.name, binding.columnName,
                    binding.confidence, binding.method,
                )
            else:
                result.pending.append(binding)
                logger.debug(
                    "Pending review: %s → %s (%.2f, %s)",
                    entity.name, binding.columnName,
                    binding.confidence, binding.method,
                )

        logger.info(
            "Binding complete: %d accepted, %d pending, %d unresolved",
            len(result.bindings), len(result.pending), len(result.unresolved),
        )
        return result

    def accept_pending(
        self, result: BindingResult, entity_id: str, column: str | None = None
    ) -> BindingResult:
        """Accept a pending binding (optionally with user override)."""
        for i, b in enumerate(result.pending):
            if b.entityId == entity_id:
                binding = result.pending.pop(i)
                if column and column != binding.columnName:
                    binding.userOverride = column
                binding.autoAccepted = False  # user-accepted
                result.bindings.append(binding)
                break
        return result

    def reject_pending(self, result: BindingResult, entity_id: str) -> BindingResult:
        """Reject a pending binding — moves to unresolved."""
        for i, b in enumerate(result.pending):
            if b.entityId == entity_id:
                result.pending.pop(i)
                result.unresolved.append(entity_id)
                break
        return result


def bind_template(
    topics: list[TopicNode],
    entities: list[TemplateEntity],
    schema: DatasetSchema,
    *,
    template_id: str = "default",
) -> BindingResult:
    """Module-level convenience function for template binding."""
    binder = TemplateBinder()
    return binder.bind(topics, entities, schema, template_id=template_id)
