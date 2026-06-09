"""R2 — PDF export for the render layer.

Primary engine is **WeasyPrint** (HTML/CSS → PDF, CSS Paged Media). It consumes
the exact R1 HTML, so the ``@page`` running header/footer, page counters, cover,
TOC, figure/table numbering and repeating table headers all carry through with
no second code path. A premium **LaTeX/Tectonic** engine is wired in R6.

WeasyPrint needs native libraries (Pango/Cairo) that are not always present —
especially on Windows — so every entry point degrades gracefully: callers get
``None`` (or a clear availability flag) instead of an exception, and the API
layer turns that into a ``503`` rather than a crash.

For PDF, document chrome (cover / TOC / provenance appendix / numbering) defaults
**on**, since a downloadable report is the formal deliverable.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_ENGINES = ("weasyprint", "latex")
DEFAULT_ENGINE = "weasyprint"


def pdf_available(engine: str = DEFAULT_ENGINE) -> bool:
    """True iff the given PDF engine can actually produce output on this host."""
    if engine == "weasyprint":
        try:
            import weasyprint  # type: ignore  # noqa: F401
            return True
        except Exception:  # pragma: no cover - depends on host libs
            return False
    if engine == "latex":
        try:
            from .latex import tectonic_available  # type: ignore
            return tectonic_available()
        except Exception:
            return False
    return False


def render_pdf(
    report: dict[str, Any],
    *,
    title: str | None = None,
    theme: Any = None,
    locale: str = "en-IN",
    number_system: str = "indian",
    engine: str = DEFAULT_ENGINE,
    include_cover: bool = True,
    include_toc: bool = True,
    include_appendix: bool = True,
    number_elements: bool = True,
) -> bytes | None:
    """Render ``report`` to PDF bytes, or ``None`` when the engine is unavailable.

    ``engine`` selects the backend (``weasyprint`` default; ``latex`` in R6).
    Unknown engines raise :class:`ValueError`.
    """
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(
            f"unknown PDF engine {engine!r}; supported: {', '.join(SUPPORTED_ENGINES)}"
        )

    if engine == "latex":
        try:
            from .latex import render_pdf_latex  # type: ignore
        except Exception as exc:  # pragma: no cover - R6 optional
            logger.info("[render] latex engine unavailable: %s", exc)
            return None
        return render_pdf_latex(
            report, title=title, theme=theme, locale=locale,
            include_cover=include_cover, include_toc=include_toc,
            include_appendix=include_appendix, number_elements=number_elements,
        )
    # WeasyPrint path.
    try:
        from weasyprint import HTML  # type: ignore
    except Exception as exc:  # pragma: no cover - optional native dep
        logger.info("[render] PDF skipped (WeasyPrint unavailable): %s", exc)
        return None

    from ..renderer import render_html
    html_str = render_html(
        report, title=title, theme=theme, locale=locale,
        number_system=number_system,
        include_cover=include_cover, include_toc=include_toc,
        include_appendix=include_appendix, number_elements=number_elements,
    )
    return HTML(string=html_str).write_pdf()
