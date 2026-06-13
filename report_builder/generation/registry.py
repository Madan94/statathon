"""FormulaRegistry — dynamic dispatch from `formulaSpec.type` to a handler.

The same key-dispatch idiom as `analytics_engine/router.py::resolve_block_analytics`,
but registration is **open**: a handler declares the types it serves with the
`@FormulaRegistry.register("SHARE", ...)` decorator. Adding a new formula family is
a new handler + a registration line — never an edit to a central if/elif chain.

A handler has the signature::

    handler(plan: AdaptedPlan, df: pd.DataFrame, profile: GenerationConfig) -> FormulaResult

`resolve` always returns *something* (it falls back to the DIRECT handler) so the
coordinator can route any plan without first checking membership.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # avoid import cycle at runtime (handlers live in formula_exec)
    import pandas as pd

    from report_builder.generation.bundle_adapter import AdaptedPlan
    from report_builder.generation.config import GenerationConfig
    from report_builder.generation.formula_exec import FormulaResult

    FormulaHandler = Callable[[AdaptedPlan, pd.DataFrame, GenerationConfig], FormulaResult]


class FormulaRegistry:
    """Process-wide registry mapping an uppercase formula type → its handler."""

    _handlers: dict[str, "FormulaHandler"] = {}
    _fallback: str = "DIRECT"

    @classmethod
    def register(cls, *types: str) -> Callable[["FormulaHandler"], "FormulaHandler"]:
        """Decorator: register ``fn`` for one or more formula types (case-insensitive)."""
        def deco(fn: "FormulaHandler") -> "FormulaHandler":
            for t in types:
                cls._handlers[t.upper()] = fn
            return fn
        return deco

    @classmethod
    def get(cls, ftype: str | None) -> "FormulaHandler | None":
        """Return the exact handler for ``ftype`` (or None if unregistered)."""
        return cls._handlers.get((ftype or "").upper())

    @classmethod
    def resolve(cls, ftype: str | None) -> "FormulaHandler":
        """Return the handler for ``ftype``, falling back to the DIRECT handler."""
        handler = cls.get(ftype)
        if handler is None:
            handler = cls._handlers[cls._fallback]
        return handler

    @classmethod
    def types(cls) -> list[str]:
        return sorted(cls._handlers)
