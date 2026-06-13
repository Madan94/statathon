"""Entity extraction sub-package."""
from template_engine.extraction.entity_extractor import extract_entities
from template_engine.extraction.entity_classifier import classify_entity_type
from template_engine.extraction.entity_deduplicator import deduplicate_entities

__all__ = ["extract_entities", "classify_entity_type", "deduplicate_entities"]
