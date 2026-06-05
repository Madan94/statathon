"""LaTeX Renderer — Jinja2 → .tex → lualatex → PDF; Pandoc → HTML.

Renders report content into LaTeX using Jinja2 templates, then compiles
to PDF via lualatex. Also supports HTML preview via Pandoc conversion.

Output structure:
  report_<id>/
    report.tex        — Main LaTeX file
    report.pdf        — Compiled PDF
    report.html       — HTML preview (optional)
    figures/          — Charts and images
    tables/           — Standalone table fragments

Template hierarchy:
  templates/
    base.tex.j2       — Document class, preamble, structure
    topic.tex.j2      — Topic section template
    question.tex.j2   — Question block (narrative + components)
    table.tex.j2      — Data table component
    kpi.tex.j2        — KPI card component
    chart.tex.j2      — Chart placeholder/inclusion
"""
from __future__ import annotations

import logging
import os
import subprocess
import shutil
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

logger = logging.getLogger(__name__)

# Default template directory
_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates" / "latex"


class LaTeXRenderer:
    """Renders report results into LaTeX → PDF."""

    def __init__(
        self,
        template_dir: Path | None = None,
        output_dir: Path | None = None,
    ):
        self._template_dir = template_dir or _TEMPLATE_DIR
        self._output_dir = output_dir or Path("outputs")
        self._env: Any = None

        if HAS_JINJA2 and self._template_dir.exists():
            self._env = Environment(
                loader=FileSystemLoader(str(self._template_dir)),
                autoescape=select_autoescape([]),
                block_start_string="\\BLOCK{",
                block_end_string="}",
                variable_start_string="\\VAR{",
                variable_end_string="}",
                comment_start_string="\\#{",
                comment_end_string="}",
            )

    def render(
        self,
        report_result: Any,
        *,
        report_id: str | None = None,
        compile_pdf: bool = True,
        generate_html: bool = False,
    ) -> dict[str, Path]:
        """Render report to LaTeX and optionally compile to PDF/HTML.

        Args:
            report_result: ReportResult from orchestrator
            report_id: Override report ID
            compile_pdf: Whether to compile .tex → .pdf via lualatex
            generate_html: Whether to generate HTML preview via Pandoc

        Returns:
            Dict with paths: {"tex": ..., "pdf": ..., "html": ...}
        """
        rid = report_id or getattr(report_result, "reportId", "report")
        report_dir = self._output_dir / f"report_{rid}"
        report_dir.mkdir(parents=True, exist_ok=True)

        # Generate LaTeX
        tex_content = self._render_latex(report_result)
        tex_path = report_dir / "report.tex"
        tex_path.write_text(tex_content, encoding="utf-8")

        outputs: dict[str, Path] = {"tex": tex_path}

        # Compile to PDF
        if compile_pdf:
            pdf_path = self._compile_pdf(tex_path, report_dir)
            if pdf_path:
                outputs["pdf"] = pdf_path

        # Generate HTML
        if generate_html:
            html_path = self._generate_html(tex_path, report_dir)
            if html_path:
                outputs["html"] = html_path

        logger.info("Rendered report %s: %s", rid, list(outputs.keys()))
        return outputs

    def _render_latex(self, report_result: Any) -> str:
        """Generate LaTeX content from report result."""
        if self._env and (self._template_dir / "base.tex.j2").exists():
            return self._render_with_templates(report_result)
        else:
            return self._render_standalone(report_result)

    def _render_with_templates(self, report_result: Any) -> str:
        """Render using Jinja2 templates."""
        template = self._env.get_template("base.tex.j2")
        return template.render(
            report=report_result,
            topics=getattr(report_result, "topics", []),
        )

    def _render_standalone(self, report_result: Any) -> str:
        """Generate standalone LaTeX without external templates."""
        lines = [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{booktabs}",
            r"\usepackage{longtable}",
            r"\usepackage{graphicx}",
            r"\usepackage{hyperref}",
            r"\usepackage{geometry}",
            r"\geometry{margin=2.5cm}",
            r"\usepackage{fancyhdr}",
            r"\pagestyle{fancy}",
            r"\fancyhead[L]{PLFS Quarterly Report}",
            r"\fancyhead[R]{\thepage}",
            "",
            r"\title{Periodic Labour Force Survey --- Quarterly Report}",
            r"\author{Generated by StatAthon Report Engine}",
            r"\date{\today}",
            "",
            r"\begin{document}",
            r"\maketitle",
            r"\tableofcontents",
            r"\newpage",
            "",
        ]

        # Render each topic as a section
        topics = getattr(report_result, "topics", [])
        for topic in topics:
            title = getattr(topic, "title", "Topic")
            lines.append(f"\\section{{{_escape_latex(title)}}}")
            lines.append("")

            questions = getattr(topic, "questions", [])
            for q in questions:
                intent = getattr(q, "intent", "")
                narrative = getattr(q, "narrative", "")
                if intent:
                    lines.append(f"\\subsection{{{_escape_latex(intent)}}}")
                if narrative:
                    lines.append(_escape_latex(narrative))
                    lines.append("")

                # Render components
                components = getattr(q, "components", [])
                for comp in components:
                    comp_type = comp.get("type", "") if isinstance(comp, dict) else ""
                    data = comp.get("data", {}) if isinstance(comp, dict) else {}

                    if comp_type == "data_table" and data:
                        lines.extend(self._render_table(data))
                    elif comp_type == "kpi_card" and data:
                        lines.extend(self._render_kpi(data))

                lines.append("")

        lines.extend([
            "",
            r"\end{document}",
        ])
        return "\n".join(lines)

    def _render_table(self, data: dict[str, Any]) -> list[str]:
        """Render a data table as LaTeX longtable."""
        headers = data.get("headers", [])
        rows = data.get("rows", [])
        if not headers:
            return []

        n_cols = len(headers)
        col_spec = "l" + "r" * (n_cols - 1)

        lines = [
            "",
            f"\\begin{{longtable}}{{{col_spec}}}",
            "\\toprule",
            " & ".join(_escape_latex(h) for h in headers) + " \\\\",
            "\\midrule",
            "\\endhead",
        ]
        for row in rows[:30]:  # Limit rows
            cells = [_escape_latex(str(c)) for c in row[:n_cols]]
            while len(cells) < n_cols:
                cells.append("")
            lines.append(" & ".join(cells) + " \\\\")

        lines.extend([
            "\\bottomrule",
            "\\end{longtable}",
            "",
        ])
        return lines

    def _render_kpi(self, data: dict[str, Any]) -> list[str]:
        """Render a KPI card as a formatted box."""
        value = data.get("value", "")
        label = data.get("label", "")
        unit = data.get("unit", "")

        display = f"{value}{unit}" if unit else str(value)
        return [
            "",
            r"\begin{center}",
            f"\\textbf{{\\Large {_escape_latex(display)}}}\\\\",
            f"\\textit{{{_escape_latex(label)}}}",
            r"\end{center}",
            "",
        ]

    def _compile_pdf(self, tex_path: Path, output_dir: Path) -> Path | None:
        """Compile .tex to .pdf using lualatex."""
        lualatex = shutil.which("lualatex")
        if not lualatex:
            logger.warning("lualatex not found; skipping PDF compilation")
            return None

        try:
            result = subprocess.run(
                [lualatex, "-interaction=nonstopmode", "-output-directory",
                 str(output_dir), str(tex_path)],
                capture_output=True, text=True, timeout=120,
                cwd=str(output_dir),
            )
            # Run twice for TOC
            subprocess.run(
                [lualatex, "-interaction=nonstopmode", "-output-directory",
                 str(output_dir), str(tex_path)],
                capture_output=True, text=True, timeout=120,
                cwd=str(output_dir),
            )
            pdf_path = output_dir / "report.pdf"
            if pdf_path.exists():
                return pdf_path
            else:
                logger.warning("PDF not generated: %s", result.stderr[:500])
                return None
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("PDF compilation failed: %s", exc)
            return None

    def _generate_html(self, tex_path: Path, output_dir: Path) -> Path | None:
        """Generate HTML preview using Pandoc."""
        pandoc = shutil.which("pandoc")
        if not pandoc:
            logger.warning("pandoc not found; skipping HTML generation")
            return None

        html_path = output_dir / "report.html"
        try:
            subprocess.run(
                [pandoc, str(tex_path), "-o", str(html_path),
                 "--standalone", "--mathjax"],
                capture_output=True, text=True, timeout=60,
            )
            if html_path.exists():
                return html_path
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("HTML generation failed: %s", exc)
        return None


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters."""
    if not text:
        return ""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def render_report(
    report_result: Any,
    *,
    output_dir: Path | None = None,
    compile_pdf: bool = True,
    generate_html: bool = False,
) -> dict[str, Path]:
    """Module-level convenience for rendering."""
    renderer = LaTeXRenderer(output_dir=output_dir)
    return renderer.render(
        report_result,
        compile_pdf=compile_pdf,
        generate_html=generate_html,
    )
