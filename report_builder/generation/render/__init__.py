"""Render layer for the generation phase (R1+).

Turns ``report.output.ast.json`` into MoSPI-grade HTML / PDF. Built incrementally:

    R1.1  numbers.py (value formatting) + theme.py (theme registry)   ← here
    R1.2  svg_charts.py   (7 chart types + density)
    R1.3  tables.py       (column groups, subtotals, header-repeat, footnotes)
    R1.4  document.py     (cover, TOC, header/footer, page numbers, numbering)
    R1.5  blocks.py       (per-question groups) + bilingual labels

Public API is kept stable throughout — ``render_html`` / ``render_pdf`` remain
importable from ``report_builder.generation``. During the migration these are
re-exported from the legacy ``renderer`` module; later sub-phases move the
implementation into this package.
"""
from __future__ import annotations

from typing import Any

from .numbers import format_value, parse_format, esc, EM_DASH
from .theme import Theme, THEMES, DEFAULT_THEME_ID, get_theme, theme_css

__all__ = [
    "render_html",
    "render_pdf",
    "format_value",
    "parse_format",
    "esc",
    "EM_DASH",
    "Theme",
    "THEMES",
    "DEFAULT_THEME_ID",
    "get_theme",
    "theme_css",
]


def render_html(*args: Any, **kwargs: Any) -> str:
    """Lazy facade → ``renderer.render_html`` (avoids a package-init import cycle)."""
    from ..renderer import render_html as _impl
    return _impl(*args, **kwargs)


def render_pdf(*args: Any, **kwargs: Any):
    """Lazy facade → ``renderer.render_pdf`` (avoids a package-init import cycle)."""
    from ..renderer import render_pdf as _impl
    return _impl(*args, **kwargs)
