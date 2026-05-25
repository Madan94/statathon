"""Generate a synthetic MoSPI-style PDF and verify Phase 0 template extraction."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(_ROOT / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
)
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402

from report_builder import blueprint as bp  # noqa: E402


def make_synthetic_mospi_pdf(out_path: Path) -> Path:
    """Build a fake old-style MoSPI PDF with headings/tables/paragraphs."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Periodic Labour Force Survey — Quarterly Bulletin",
    )
    styles = getSampleStyleSheet()
    story = []

    # Cover-ish heading
    story.append(Paragraph(
        "Ministry of Statistics and Programme Implementation",
        styles["Title"],
    ))
    story.append(Paragraph(
        "PERIODIC LABOUR FORCE SURVEY",
        styles["Heading1"],
    ))
    story.append(Paragraph(
        "Quarterly Bulletin — October–December 2025",
        styles["Heading2"],
    ))
    story.append(Spacer(1, 8 * mm))

    # Section 1 — Executive Summary (narrative)
    story.append(Paragraph("EXECUTIVE SUMMARY", styles["Heading1"]))
    story.append(Paragraph(
        "This bulletin presents key indicators of the labour market in urban "
        "areas of India for the quarter October–December 2025, based on the "
        "Periodic Labour Force Survey (PLFS). Estimates are derived using "
        "Current Weekly Status (CWS) and presented for persons aged 15 years "
        "and above.",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 4 * mm))

    # Section 2 — Coverage and Methodology
    story.append(Paragraph("COVERAGE AND METHODOLOGY", styles["Heading1"]))
    story.append(Paragraph(
        "The survey covered 5,500 first-stage units selected through "
        "stratified multi-stage sampling. Data was collected from approximately "
        "44,000 households across all states and Union Territories.",
        styles["BodyText"],
    ))
    story.append(PageBreak())

    # Section 3 — Key Estimates (table)
    story.append(Paragraph("KEY LABOUR FORCE INDICATORS", styles["Heading1"]))
    story.append(Paragraph(
        "Estimates of the Labour Force Participation Rate (LFPR), Worker "
        "Population Ratio (WPR), and Unemployment Rate (UR) are tabulated "
        "below for the reference period.",
        styles["BodyText"],
    ))
    data = [
        ["Indicator", "Male", "Female", "Persons"],
        ["LFPR (%)", "73.8", "25.2", "49.9"],
        ["WPR (%)", "70.6", "23.5", "47.4"],
        ["UR (%)", "4.4", "6.8", "5.0"],
    ]
    t = Table(data, hAlign="LEFT", colWidths=[70 * mm, 25 * mm, 25 * mm, 25 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3B7A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 10),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#888")),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # Section 4 — Findings (narrative)
    story.append(Paragraph("KEY FINDINGS", styles["Heading1"]))
    story.append(Paragraph(
        "Female participation in the labour force registered an increase "
        "compared with the corresponding quarter of the previous year, "
        "reflecting improved economic conditions and policy interventions "
        "aimed at women's employment.",
        styles["BodyText"],
    ))
    story.append(PageBreak())

    # Section 5 — State-wise Estimates (another table)
    story.append(Paragraph("STATE-WISE ESTIMATES", styles["Heading1"]))
    sw = [
        ["State", "LFPR (%)", "UR (%)"],
        ["Maharashtra", "51.2", "4.1"],
        ["Tamil Nadu", "49.8", "3.9"],
        ["West Bengal", "47.5", "5.2"],
        ["Karnataka", "50.6", "4.3"],
    ]
    t2 = Table(sw, hAlign="LEFT", colWidths=[80 * mm, 30 * mm, 30 * mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3B7A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 10),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#888")),
    ]))
    story.append(t2)
    story.append(Spacer(1, 6 * mm))

    # Section 6 — Recommendations
    story.append(Paragraph("RECOMMENDATIONS AND CONCLUSIONS", styles["Heading1"]))
    story.append(Paragraph(
        "Continued investment in skill development, targeted interventions "
        "for women's labour participation, and strengthening of MSMEs will "
        "be critical for sustaining the observed improvements in the labour "
        "market.",
        styles["BodyText"],
    ))

    doc.build(story)
    return out_path


def main() -> int:
    pdf_path = _ROOT / "storage" / "templates" / "synthetic_mospi_plfs.pdf"
    make_synthetic_mospi_pdf(pdf_path)
    print(f"\nGenerated synthetic MoSPI PDF: {pdf_path} ({pdf_path.stat().st_size} bytes)\n")

    ast = bp.compile_template(pdf_path, template_name="PLFS Quarterly (synthetic)")
    payload = ast.to_dict()

    print("=== AST extraction result ===")
    print(f"  name            : {payload['name']}")
    print(f"  page_count      : {payload['page_count']}")
    print(f"  extraction_method: {payload['extraction_method']}")
    print(f"  source_hash     : {payload['source_hash'][:24] if payload['source_hash'] else None}...")
    print(f"  block_count     : {len(payload['blocks'])}")
    print("\n  Detected blocks:")
    for b in payload["blocks"]:
        print(f"    - [{b['kind']:<9}] {b['section']:<28} -> {b['title']}")

    # Verify the round-trip back into TemplateAST works
    rebuilt = bp.template_from_ast_json(payload)
    print(f"\n  Round-trip OK: {len(rebuilt.blocks)} blocks reconstructed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
