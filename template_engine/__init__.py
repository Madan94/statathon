"""Template Engine — Phase 0: Reverse-Engineering & Template Blueprinting.

Entry points:
  compile_template(pdf_path, name) -> TemplateAST   # full pipeline
  load_default_mospi()             -> TemplateAST   # builtin fallback
"""
from template_engine.ast.ast_builder import compile_template
from template_engine.ast.template_serializer import (
    serialize_template,
    deserialize_template,
    load_default_mospi,
)

__all__ = [
    "compile_template",
    "serialize_template",
    "deserialize_template",
    "load_default_mospi",
]
