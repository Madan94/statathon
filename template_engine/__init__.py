"""Template Engine — Phase 0: Reverse-Engineering & Template Blueprinting.

Enhanced Pipeline (Vision-Spatial):
  run_extraction_pipeline(pdf_path, name) -> ExtractionResult   # full deep pipeline
  compile_template(pdf_path, name)        -> TemplateAST        # legacy compat

Legacy (backward compat):
  load_default_mospi()                    -> TemplateAST        # builtin fallback
"""
from template_engine.ast.ast_builder import compile_template
from template_engine.ast.template_serializer import (
    serialize_template,
    deserialize_template,
    load_default_mospi,
)
from template_engine.pipeline import run_extraction_pipeline, ExtractionResult

__all__ = [
    "compile_template",
    "serialize_template",
    "deserialize_template",
    "load_default_mospi",
    "run_extraction_pipeline",
    "ExtractionResult",
]
