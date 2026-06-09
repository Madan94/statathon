"""R6 — premium LaTeX / Tectonic PDF engine (optional).

Produces a ``.tex`` document from ``report.output.ast.json`` and compiles it with
the single-binary `Tectonic <https://tectonic-typesetting.github.io/>`_ engine.
Long tables use ``longtable`` + ``booktabs`` so headers repeat natively across
page breaks (matching the MoSPI statistical-chapter archetype).

This engine is *opt-in*: ``render_pdf(..., engine="latex")`` routes here while the
default stays WeasyPrint. Every entry point degrades gracefully — if Tectonic is
not installed, the compile step returns ``None`` (the API turns that into a
``503``) instead of raising.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any, Optional

from .numbers import format_value, loc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def tectonic_available() -> bool:
    """True iff the ``tectonic`` binary is on PATH."""
    return shutil.which("tectonic") is not None


# ---------------------------------------------------------------------------
# Escaping / formatting
# ---------------------------------------------------------------------------

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _esc(text: Any) -> str:
    """Escape a string for LaTeX body text."""
    out = []
    for ch in str(text if text is not None else ""):
        out.append(_LATEX_SPECIALS.get(ch, ch))
    return "".join(out)


def _fmt(value: Any, unit: Optional[str], fmt: Optional[str], system: str) -> str:
    return _esc(format_value(value, unit=unit, fmt=fmt, system=system))


def _index(items: list[dict], key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in items or []:
        k = item.get(key)
        if k:
            out[k] = item
    return out


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _col_align(col: dict) -> str:
    if col.get("align") == "right" or col.get("role") == "measure":
        return "r"
    if col.get("align") == "center":
        return "c"
    return "l"


def _render_table(table: dict, locale: str, system: str) -> str:
    columns = table.get("columns") or []
    if not columns:
        return ""
    rows = table.get("rows") or []
    spec = "".join(_col_align(c) for c in columns)
    headers = " & ".join(f"\\textbf{{{_esc(loc(c.get('header'), locale))}}}" for c in columns)
    ncol = len(columns)

    lines = [f"\\begin{{longtable}}{{{spec}}}"]
    title = loc(table.get("title"), locale)
    if title:
        lines.append(f"\\caption{{{_esc(title)}}}\\\\")
    lines += [
        "\\toprule",
        f"{headers} \\\\",
        "\\midrule",
        "\\endfirsthead",
        "\\toprule",
        f"{headers} \\\\",
        "\\midrule",
        "\\endhead",
        "\\midrule",
        f"\\multicolumn{{{ncol}}}{{r}}{{\\textit{{continued on next page}}}}\\\\",
        "\\endfoot",
        "\\bottomrule",
        "\\endlastfoot",
    ]
    for row in rows:
        cells = []
        for col in columns:
            cid = col.get("columnId")
            raw = row.get(cid)
            if col.get("role") == "measure":
                cells.append(_fmt(raw, col.get("unit"), col.get("format"), system))
            else:
                cells.append(_esc(loc(raw, locale)) if raw is not None else "\u2014")
        prefix = "\\textbf{" if (row.get("isTotal") or row.get("isSubtotal")) else ""
        joined = " & ".join((prefix + c + "}") if prefix else c for c in cells)
        lines.append(f"{joined} \\\\")
    lines.append("\\end{longtable}")

    for fn in table.get("footnotes") or []:
        txt = loc(fn.get("text"), locale)
        if txt:
            lines.append(f"{{\\footnotesize {_esc(txt)}}}\\\\")
    return "\n".join(lines)


def _render_section(sec: dict, report: dict, maps: dict, locale: str, system: str) -> str:
    out = [f"\\section{{{_esc(loc(sec.get('title'), locale))}}}"]
    for child in sec.get("children") or []:
        block = maps["blocks"].get(child)
        if block is not None:
            content = loc(block.get("content"), locale)
            if content:
                out.append(_esc(content))
            continue
        figure = maps["figures"].get(child)
        if figure is not None:
            caption = loc(figure.get("caption"), locale)
            # Charts are not embedded for LaTeX (no plot toolchain dependency);
            # the caption preserves the figure's place in the narrative.
            out.append(f"\\begin{{quote}}\\textit{{[Figure: {_esc(caption)}]}}\\end{{quote}}")
            continue
        table = maps["tables"].get(child)
        if table is not None:
            out.append(_render_table(table, locale, system))
    return "\n\n".join(out)


def _preamble() -> str:
    return "\n".join([
        "\\documentclass[11pt]{article}",
        "\\usepackage{geometry}",
        "\\geometry{a4paper,margin=2.2cm}",
        "\\usepackage{booktabs}",
        "\\usepackage{longtable}",
        "\\usepackage{array}",
        "\\usepackage{graphicx}",
        "\\usepackage{xcolor}",
        "\\usepackage[colorlinks=true,linkcolor=black]{hyperref}",
        "\\setlength{\\parskip}{0.6em}",
        "\\setlength{\\parindent}{0pt}",
    ])


def render_latex(
    report: dict[str, Any],
    *,
    title: Optional[str] = None,
    theme: Any = None,
    locale: str = "en-IN",
    number_system: str = "indian",
    include_cover: bool = True,
    include_toc: bool = True,
    include_appendix: bool = True,
    number_elements: bool = True,
) -> str:
    """Render the report to a LaTeX ``.tex`` document string."""
    sections = sorted(
        (report.get("semanticAST") or {}).get("sections") or [],
        key=lambda s: s.get("order", 0),
    )
    maps = {
        "blocks": _index((report.get("contentAST") or {}).get("blocks"), "blockId"),
        "figures": _index((report.get("figureAST") or {}).get("figures"), "figureId"),
        "tables": _index((report.get("tableAST") or {}).get("tables"), "tableId"),
    }

    doc_title = title or (loc(sections[0].get("title"), locale) if sections else "Statistical Report")
    metadata = report.get("metadata") or {}
    period = (metadata.get("period") or {}).get("current") or ""

    parts = [_preamble(), "\\begin{document}"]

    if include_cover:
        parts.append("\\begin{titlepage}\\centering\\vspace*{4cm}")
        parts.append(f"{{\\Huge\\bfseries {_esc(doc_title)}\\par}}")
        if period:
            parts.append(f"\\vspace{{1cm}}{{\\large Reference period: {_esc(period)}\\par}}")
        if metadata.get("reportId"):
            parts.append(f"\\vspace{{0.5cm}}{{\\normalsize Report ID: {_esc(metadata['reportId'])}\\par}}")
        parts.append("\\vfill\\end{titlepage}")
    else:
        parts.append(f"\\title{{{_esc(doc_title)}}}\\date{{}}\\maketitle")

    if include_toc:
        parts.append("\\tableofcontents\\newpage")

    for sec in sections:
        parts.append(_render_section(sec, report, maps, locale, number_system))

    parts.append("\\end{document}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def compile_pdf_tectonic(tex: str) -> Optional[bytes]:
    """Compile a ``.tex`` string to PDF bytes with Tectonic, or ``None``."""
    if not tectonic_available():
        logger.info("[render] LaTeX skipped (Tectonic not on PATH)")
        return None
    with tempfile.TemporaryDirectory() as d:
        tex_path = os.path.join(d, "report.tex")
        with open(tex_path, "w", encoding="utf-8") as fh:
            fh.write(tex)
        try:
            subprocess.run(
                ["tectonic", tex_path, "--outdir", d, "--chatter", "minimal"],
                check=True, capture_output=True, timeout=180,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - host dep
            logger.warning("[render] Tectonic compile failed: %s", exc)
            return None
        pdf_path = os.path.join(d, "report.pdf")
        if not os.path.exists(pdf_path):
            return None
        with open(pdf_path, "rb") as fh:
            return fh.read()


def render_pdf_latex(
    report: dict[str, Any],
    *,
    title: Optional[str] = None,
    theme: Any = None,
    locale: str = "en-IN",
    number_system: str = "indian",
    include_cover: bool = True,
    include_toc: bool = True,
    include_appendix: bool = True,
    number_elements: bool = True,
) -> Optional[bytes]:
    """Render → compile in one step; ``None`` when Tectonic is unavailable."""
    tex = render_latex(
        report, title=title, theme=theme, locale=locale, number_system=number_system,
        include_cover=include_cover, include_toc=include_toc,
        include_appendix=include_appendix, number_elements=number_elements,
    )
    return compile_pdf_tectonic(tex)
