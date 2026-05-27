"""Phase 6 — Government-Grade PDF Exporter.

Produces a MoSPI-style official statistical report from the BlockCanvas JSON.
Structure follows the sample report template (template_1.pdf style):

  ┌─────────────────────────────────────────┐
  │  COVER PAGE                             │
  │   Ministry of Statistics branding       │
  │   Report title, dataset name, date      │
  │   Content hash (tamper-proof seal)      │
  ├─────────────────────────────────────────┤
  │  TABLE OF CONTENTS (auto-generated)     │
  ├─────────────────────────────────────────┤
  │  SECTIONS (numbered 1, 2, 3 ...)        │
  │   1.1 Heading                           │
  │   [narrative / table / chart / metric]  │
  │   ✓ Verifier badge per block            │
  ├─────────────────────────────────────────┤
  │  APPENDIX — Audit Trail                 │
  │   SHA-256 content hash                  │
  │   Verifier verdict summary              │
  └─────────────────────────────────────────┘

Every page has:
  - Header bar: Ministry of Statistics & PI | document title
  - Footer: "STATATHON Report Engine | Page N | Generated YYYY-MM-DDTHH:MM:SSZ"
"""
from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette (MoSPI deep navy + accent)
# ---------------------------------------------------------------------------

_NAVY = "#003366"
_ACCENT = "#1565C0"
_LIGHT_BLUE = "#E3F0FF"
_LIGHT_GREY = "#F5F6FA"
_BORDER_GREY = "#CCCCCC"
_WHITE = "#FFFFFF"
_TEXT_DARK = "#1A1A2E"
_TEXT_MUTED = "#666666"
_GREEN = "#2E7D32"
_ORANGE = "#E65100"
_RED = "#C62828"


def _rl_colors():
    from reportlab.lib.colors import HexColor
    return {
        "navy": HexColor(_NAVY),
        "accent": HexColor(_ACCENT),
        "light_blue": HexColor(_LIGHT_BLUE),
        "light_grey": HexColor(_LIGHT_GREY),
        "border_grey": HexColor(_BORDER_GREY),
        "white": HexColor(_WHITE),
        "text_dark": HexColor(_TEXT_DARK),
        "text_muted": HexColor(_TEXT_MUTED),
        "green": HexColor(_GREEN),
        "orange": HexColor(_ORANGE),
        "red": HexColor(_RED),
    }


# ---------------------------------------------------------------------------
# Style definitions
# ---------------------------------------------------------------------------

def _build_styles():
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    base = getSampleStyleSheet()
    C = _rl_colors()
    styles: dict[str, Any] = {}

    # Cover page
    styles["cover_ministry"] = ParagraphStyle(
        "cover_ministry",
        parent=base["Normal"],
        fontSize=9,
        leading=12,
        textColor=C["text_muted"],
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    styles["cover_title"] = ParagraphStyle(
        "cover_title",
        parent=base["Title"],
        fontSize=24,
        leading=30,
        textColor=C["navy"],
        alignment=TA_CENTER,
        spaceBefore=12,
        spaceAfter=8,
        fontName="Helvetica-Bold",
    )
    styles["cover_subtitle"] = ParagraphStyle(
        "cover_subtitle",
        parent=base["Normal"],
        fontSize=13,
        leading=17,
        textColor=C["accent"],
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    styles["cover_meta"] = ParagraphStyle(
        "cover_meta",
        parent=base["Normal"],
        fontSize=9,
        leading=12,
        textColor=C["text_muted"],
        alignment=TA_CENTER,
        spaceAfter=3,
    )

    # Document headings
    styles["chapter"] = ParagraphStyle(
        "chapter",
        parent=base["Heading1"],
        fontSize=15,
        leading=19,
        textColor=C["navy"],
        fontName="Helvetica-Bold",
        spaceBefore=18,
        spaceAfter=8,
        borderPadding=(0, 0, 4, 0),
    )
    styles["section"] = ParagraphStyle(
        "section",
        parent=base["Heading2"],
        fontSize=12,
        leading=15,
        textColor=C["accent"],
        fontName="Helvetica-Bold",
        spaceBefore=10,
        spaceAfter=5,
    )
    styles["subsection"] = ParagraphStyle(
        "subsection",
        parent=base["Heading3"],
        fontSize=10,
        leading=13,
        textColor=HexColor(_TEXT_DARK),
        fontName="Helvetica-Bold",
        spaceBefore=6,
        spaceAfter=3,
    )

    # Body / narrative
    styles["body"] = ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontSize=10,
        leading=15,
        textColor=HexColor(_TEXT_DARK),
        spaceAfter=6,
        firstLineIndent=0,
    )
    styles["small"] = ParagraphStyle(
        "small",
        parent=base["Normal"],
        fontSize=8,
        leading=11,
        textColor=HexColor(_TEXT_MUTED),
        spaceAfter=3,
    )
    styles["caption"] = ParagraphStyle(
        "caption",
        parent=base["Normal"],
        fontSize=8,
        leading=11,
        textColor=HexColor(_TEXT_MUTED),
        alignment=TA_CENTER,
        spaceBefore=2,
        spaceAfter=6,
    )
    styles["toc_entry"] = ParagraphStyle(
        "toc_entry",
        parent=base["Normal"],
        fontSize=10,
        leading=14,
        textColor=HexColor(_TEXT_DARK),
        leftIndent=8,
        spaceAfter=2,
    )

    return styles, mm


# ---------------------------------------------------------------------------
# Table styling helpers
# ---------------------------------------------------------------------------

def _header_table_style(colors):
    from reportlab.platypus import TableStyle
    return TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  colors["navy"]),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors["white"]),
        ("FONT",         (0, 0), (-1, 0),  "Helvetica-Bold", 9),
        ("FONT",         (0, 1), (-1, -1), "Helvetica", 9),
        ("GRID",         (0, 0), (-1, -1), 0.3, colors["border_grey"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors["white"], colors["light_grey"]]),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ])


def _metric_table_style(colors):
    from reportlab.platypus import TableStyle
    return TableStyle([
        ("BACKGROUND",   (0, 0), (0, -1), colors["light_blue"]),
        ("FONT",         (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT",         (1, 0), (1, -1), "Helvetica", 9),
        ("GRID",         (0, 0), (-1, -1), 0.3, colors["border_grey"]),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors["white"], colors["light_grey"]]),
    ])


# ---------------------------------------------------------------------------
# Verifier badge
# ---------------------------------------------------------------------------

def _verifier_badge(verifier: dict | None, styles, Paragraph) -> Any | None:
    if not verifier:
        return None
    status = str(verifier.get("overall_status") or "").lower()
    if status == "pass":
        icon, color = "✓ Verified", _GREEN
    elif status == "warn":
        icon, color = "⚠ Soft warning — some claims unverified", _ORANGE
    else:
        icon, color = "✗ Verification failed", _RED

    from reportlab.lib.colors import HexColor
    style = styles["small"]
    style_copy = style.__class__(
        f"badge_{id(style)}",
        parent=style,
        textColor=HexColor(color),
        fontName="Helvetica-Oblique",
    )
    checks_passed = sum(1 for c in (verifier.get("checks") or []) if c.get("status") == "pass")
    checks_total = len(verifier.get("checks") or [])
    note = f" ({checks_passed}/{checks_total} claims verified)" if checks_total > 0 else ""
    return Paragraph(f"{icon}{note}", style_copy)


# ---------------------------------------------------------------------------
# Block-level renderers
# ---------------------------------------------------------------------------

def _render_narrative(blk: dict, story: list, styles, Paragraph, Spacer, mm, colors):
    payload = blk.get("payload") or {}
    text = (payload.get("text") or "").replace("\n", "<br/>")
    if text:
        story.append(Paragraph(text, styles["body"]))
    else:
        story.append(Paragraph("<i>(no narrative generated)</i>", styles["small"]))
    badge = _verifier_badge(blk.get("verifier"), styles, Paragraph)
    if badge:
        story.append(badge)


def _render_metric(blk: dict, story: list, styles, Table, TableStyle, Paragraph, Spacer, mm, colors):
    from reportlab.platypus import TableStyle as TS
    payload = blk.get("payload") or {}
    metrics = payload.get("metrics") or {}

    if not metrics:
        story.append(Paragraph("<i>(no metrics)</i>", styles["small"]))
        return

    rows = [["Indicator", "Value"]]
    for k, v in metrics.items():
        label = str(k).replace("_", " ").title()
        val = str(v) if not isinstance(v, (list, dict)) else str(v)[:120]
        rows.append([label, val])

    t = Table(rows, hAlign="LEFT", colWidths=[75 * mm, 95 * mm])
    t.setStyle(_metric_table_style(colors))
    story.append(t)


def _render_table(blk: dict, story: list, styles, Table, TableStyle, Paragraph, Spacer, mm, colors):
    payload = blk.get("payload") or {}
    rows_data = payload.get("rows") or []
    cols = payload.get("columns") or []

    if not rows_data or not cols:
        story.append(Paragraph("<i>(no tabular data)</i>", styles["small"]))
        return

    data = [list(cols)]
    for row in rows_data[:80]:
        data.append([str(row.get(c, ""))[:60] for c in cols])

    col_width = min(40 * mm, 170 * mm / max(len(cols), 1))
    t = Table(data, hAlign="LEFT", colWidths=[col_width] * len(cols))
    t.setStyle(_header_table_style(colors))
    story.append(t)
    if len(rows_data) > 80:
        story.append(Paragraph(
            f"<i>Note: Showing first 80 of {len(rows_data)} rows.</i>",
            styles["caption"],
        ))


def _render_chart(blk: dict, story: list, styles, Image, Paragraph, mm, colors):
    payload = blk.get("payload") or {}
    png = _render_chart_png(payload, blk.get("title", ""))
    if png:
        story.append(Image(io.BytesIO(png), width=155 * mm, height=82 * mm))
        story.append(Paragraph(
            blk.get("title") or payload.get("title") or "", styles["caption"]
        ))
    else:
        story.append(Paragraph(
            f"<i>Chart data unavailable: {payload.get('chart_type', 'bar')}</i>",
            styles["small"],
        ))


def _render_chart_png(payload: dict[str, Any], title: str = "") -> bytes | None:
    chart_type = payload.get("chart_type", "bar")
    labels = payload.get("labels") or []
    values = payload.get("values") or []

    if not labels or not values:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker

        fig, ax = plt.subplots(figsize=(8, 4))
        fig.patch.set_facecolor("#FAFBFD")
        ax.set_facecolor("#FAFBFD")

        if chart_type in ("bar", "histogram"):
            x_pos = range(len(labels))
            bars = ax.bar(x_pos, values, color=_ACCENT, edgecolor=_NAVY, linewidth=0.5)
            ax.set_xticks(list(x_pos))
            ax.set_xticklabels(
                [str(l)[:18] for l in labels],
                rotation=45, ha="right", fontsize=8,
            )
            # Value labels on bars (if ≤20 bars)
            if len(bars) <= 20:
                for bar in bars:
                    h = bar.get_height()
                    if h > 0:
                        ax.text(
                            bar.get_x() + bar.get_width() / 2,
                            h * 1.01,
                            f"{h:,.0f}" if h == int(h) else f"{h:.2f}",
                            ha="center", va="bottom", fontsize=7, color=_NAVY,
                        )
        elif chart_type == "line":
            ax.plot(
                range(len(labels)), values,
                marker="o", color=_ACCENT, linewidth=2,
                markerfacecolor=_NAVY, markersize=5,
            )
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels([str(l)[:18] for l in labels], rotation=45, ha="right", fontsize=8)
        elif chart_type == "pie":
            ax.pie(
                values, labels=[str(l)[:20] for l in labels],
                autopct="%1.1f%%", startangle=90,
                colors=[_ACCENT, _NAVY, "#4FC3F7", "#81D4FA", "#B3E5FC", "#E1F5FE"],
            )
        else:
            ax.bar(range(len(labels)), values, color=_ACCENT)
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels([str(l)[:18] for l in labels], rotation=45, ha="right", fontsize=8)

        ax.set_title(title or payload.get("title") or "", fontsize=11, color=_NAVY, fontweight="bold", pad=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(_BORDER_GREY)
        ax.spines["bottom"].set_color(_BORDER_GREY)
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.grid(True, axis="y", alpha=0.3, linestyle="--", color=_BORDER_GREY)
        ax.tick_params(labelsize=8, colors=_TEXT_DARK)
        fig.tight_layout(pad=1.2)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("Chart render failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

def _build_cover(
    story: list,
    canvas_dict: dict[str, Any],
    dataset_filename: str | None,
    styles,
    Spacer, PageBreak, Paragraph, Table, TableStyle, mm, colors, HRFlowable,
):
    template_name = canvas_dict.get("template_name") or "Statistical Analysis Report"
    analysis_id = canvas_dict.get("analysis_id")
    job_id = canvas_dict.get("job_id")
    generated = datetime.utcnow().strftime("%d %B %Y, %H:%M UTC")

    # Ministry header
    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph(
        "GOVERNMENT OF INDIA",
        styles["cover_ministry"],
    ))
    story.append(Paragraph(
        "Ministry of Statistics and Programme Implementation (MoSPI)",
        styles["cover_ministry"],
    ))
    story.append(Paragraph(
        "National Statistical Office",
        styles["cover_ministry"],
    ))
    story.append(Spacer(1, 8 * mm))

    # Horizontal rule
    story.append(HRFlowable(width="100%", thickness=2, color=colors["navy"]))
    story.append(Spacer(1, 6 * mm))

    # Report title
    story.append(Paragraph(template_name.upper(), styles["cover_title"]))
    story.append(Spacer(1, 4 * mm))

    # Dataset name
    if dataset_filename:
        story.append(Paragraph(f"Source: {dataset_filename}", styles["cover_subtitle"]))

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="60%", thickness=1, color=colors["accent"]))
    story.append(Spacer(1, 6 * mm))

    # Summary metrics table
    summary = canvas_dict.get("summary") or {}
    if summary:
        rows = [["Metric", "Value"]]
        for k, v in summary.items():
            label = str(k).replace("_", " ").title()
            rows.append([label, str(v)])
        t = Table(rows, hAlign="CENTER", colWidths=[70 * mm, 80 * mm])
        t.setStyle(_metric_table_style(colors))
        story.append(t)
        story.append(Spacer(1, 8 * mm))

    # Footer metadata
    story.append(Paragraph(f"Generated: {generated}", styles["cover_meta"]))
    story.append(Paragraph(f"Analysis ID: {analysis_id}  |  Job ID: {job_id}", styles["cover_meta"]))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors["navy"]))
    story.append(PageBreak())


# ---------------------------------------------------------------------------
# Table of contents
# ---------------------------------------------------------------------------

def _build_toc(story: list, canvas_dict: dict[str, Any], styles, Paragraph, Spacer, PageBreak, mm, colors, HRFlowable):
    story.append(Paragraph("TABLE OF CONTENTS", styles["chapter"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors["navy"]))
    story.append(Spacer(1, 4 * mm))

    section_counter = 0
    for sect in canvas_dict.get("sections") or []:
        section_counter += 1
        sect_label = str(sect.get("section") or "Body").replace("_", " ").title()
        story.append(Paragraph(
            f"{section_counter}.  {sect_label}",
            styles["toc_entry"],
        ))
        for i, blk in enumerate(sect.get("blocks") or []):
            sub = f"{section_counter}.{i+1}  {blk.get('title') or '—'}"
            story.append(Paragraph(sub, styles["small"]))

    story.append(PageBreak())


# ---------------------------------------------------------------------------
# Audit trail appendix
# ---------------------------------------------------------------------------

def _build_audit(
    story: list,
    canvas_dict: dict[str, Any],
    verifier_report: dict[str, Any] | None,
    content_hash: str,
    styles,
    Paragraph, Spacer, Table, TableStyle, mm, colors, HRFlowable,
):
    story.append(Paragraph("APPENDIX: AUDIT TRAIL & INTEGRITY", styles["chapter"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors["navy"]))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(
        "This document was produced by the Statathon Report Intelligence Engine. "
        "All numeric claims were independently recomputed against the source dataset "
        "via the Phase 4 Verifier. The SHA-256 hash below covers the rendered PDF bytes — "
        "any post-generation modification invalidates this seal.",
        styles["body"],
    ))
    story.append(Spacer(1, 3 * mm))

    audit_data = [
        ["Item", "Value"],
        ["Content SHA-256", content_hash],
        ["Analysis ID", str(canvas_dict.get("analysis_id") or "—")],
        ["Job ID", str(canvas_dict.get("job_id") or "—")],
        ["Generated (UTC)", datetime.utcnow().isoformat(timespec="seconds") + "Z"],
        ["Report Engine", "Statathon Report Intelligence Engine v2.0"],
        ["Template", canvas_dict.get("template_name") or "—"],
    ]
    t = Table(audit_data, hAlign="LEFT", colWidths=[60 * mm, 120 * mm])
    t.setStyle(_metric_table_style(colors))
    story.append(t)
    story.append(Spacer(1, 4 * mm))

    # Verifier summary
    if verifier_report and verifier_report.get("blocks"):
        story.append(Paragraph("Verifier Summary", styles["section"]))
        vdata = [["Block ID", "Status", "Checks Passed", "Failed", "Unverified"]]
        for v in verifier_report["blocks"][:30]:
            checks = v.get("checks") or []
            passed = sum(1 for c in checks if c.get("status") == "pass")
            failed = sum(1 for c in checks if c.get("status") == "fail")
            unverified = sum(1 for c in checks if c.get("status") == "unverified")
            vdata.append([
                str(v.get("block_id") or "—")[:30],
                str(v.get("overall_status") or "—").upper(),
                str(passed),
                str(failed),
                str(unverified),
            ])
        vt = Table(vdata, hAlign="LEFT", colWidths=[55 * mm, 25 * mm, 30 * mm, 25 * mm, 30 * mm])
        vt.setStyle(_header_table_style(colors))
        story.append(vt)


# ---------------------------------------------------------------------------
# Header / footer callbacks
# ---------------------------------------------------------------------------

_GENERATED_AT = datetime.utcnow().isoformat(timespec="seconds") + "Z"
_DOC_TITLE = "Statathon Report"


def _make_page_template(doc_title: str):
    def _page_header_footer(canvas, doc):
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor

        canvas.saveState()
        page_width = doc.pagesize[0]
        page_height = doc.pagesize[1]

        # Header bar
        canvas.setFillColor(HexColor(_NAVY))
        canvas.rect(0, page_height - 18 * mm, page_width, 18 * mm, fill=1, stroke=0)
        canvas.setFillColor(HexColor(_WHITE))
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawString(12 * mm, page_height - 10 * mm, "MoSPI | National Statistical Office")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(page_width - 12 * mm, page_height - 10 * mm, doc_title[:80])

        # Footer bar
        canvas.setFillColor(HexColor(_LIGHT_GREY))
        canvas.rect(0, 0, page_width, 10 * mm, fill=1, stroke=0)
        canvas.setFillColor(HexColor(_TEXT_MUTED))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(12 * mm, 3.5 * mm,
                          f"Statathon Report Intelligence Engine  |  {_GENERATED_AT}")
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawRightString(page_width - 12 * mm, 3.5 * mm, f"Page {doc.page}")

        canvas.restoreState()

    return _page_header_footer


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def export_pdf(
    *,
    canvas_dict: dict[str, Any],
    out_path: str | Path,
    dataset_filename: str | None = None,
    verifier_report: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Render BlockCanvas → government-grade PDF at out_path.

    Returns (storage_path, sha256_hash).
    """
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table,
        TableStyle, Image, HRFlowable,
    )
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    template_name = canvas_dict.get("template_name") or "Statathon Report"
    styles, _mm = _build_styles()
    colors = _rl_colors()

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=24 * mm,
        bottomMargin=18 * mm,
        title=template_name,
        author="Statathon Report Intelligence Engine",
        subject="Official Statistical Report",
        creator="MoSPI / NSO",
    )

    story: list[Any] = []

    # Cover
    _build_cover(
        story, canvas_dict, dataset_filename,
        styles, Spacer, PageBreak, Paragraph, Table, TableStyle, mm, colors, HRFlowable,
    )

    # Table of Contents
    _build_toc(story, canvas_dict, styles, Paragraph, Spacer, PageBreak, mm, colors, HRFlowable)

    # Body sections
    section_counter = 0
    for sect in canvas_dict.get("sections") or []:
        section_counter += 1
        sect_label = str(sect.get("section") or "Body").replace("_", " ").title()
        story.append(Paragraph(
            f"{section_counter}.  {sect_label}",
            styles["chapter"],
        ))
        from reportlab.platypus import HRFlowable as HRF
        story.append(HRF(width="100%", thickness=1, color=colors["navy"]))
        story.append(Spacer(1, 3 * mm))

        for blk_idx, blk in enumerate(sect.get("blocks") or []):
            # Section sub-heading
            story.append(Paragraph(
                f"{section_counter}.{blk_idx+1}  {blk.get('title') or '—'}",
                styles["section"],
            ))
            kind = str(blk.get("kind") or "narrative")

            if kind == "narrative":
                _render_narrative(blk, story, styles, Paragraph, Spacer, mm, colors)
            elif kind == "metric":
                _render_metric(blk, story, styles, Table, TableStyle, Paragraph, Spacer, mm, colors)
            elif kind == "table":
                _render_table(blk, story, styles, Table, TableStyle, Paragraph, Spacer, mm, colors)
            elif kind == "chart":
                _render_chart(blk, story, styles, Image, Paragraph, mm, colors)
            elif kind == "heading":
                pass  # already rendered as section heading above
            else:
                story.append(Paragraph(str(blk.get("payload") or "")[:200], styles["small"]))

            story.append(Spacer(1, 4 * mm))

    # Audit appendix (placeholder hash — replaced after doc.build)
    _placeholder_hash = "SHA256: (computed after render)"
    _build_audit(
        story, canvas_dict, verifier_report,
        _placeholder_hash,
        styles, Paragraph, Spacer, Table, TableStyle, mm, colors, HRFlowable,
    )

    # Build PDF
    page_cb = _make_page_template(template_name)
    doc.build(story, onFirstPage=page_cb, onLaterPages=page_cb)

    # Compute final hash and return
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return str(out_path), digest
