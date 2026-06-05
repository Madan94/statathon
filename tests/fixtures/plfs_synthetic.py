"""PLFS Synthetic PDF Fixture — generates a realistic PLFS-like test PDF.

Creates a multi-page PDF mimicking MoSPI PLFS quarterly bulletin structure:
  - Cover page with title
  - Table of contents
  - Statement pages with numbered tables
  - State-level data (page-spanning table)

This is used by tests to verify PLFS-specific extraction without real data.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any


def create_plfs_synthetic_pdf(output_path: Path | None = None) -> Path:
    """Create a synthetic PLFS-style PDF for testing.

    Returns path to generated PDF.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            PageBreak,
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
    except ImportError:
        # Fallback: create minimal PDF with fpdf2 or raw bytes
        return _create_minimal_plfs_pdf(output_path)

    if output_path is None:
        import tempfile
        output_path = Path(tempfile.mkdtemp()) / "plfs_synthetic.pdf"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PLFSTitle", parent=styles["Title"], fontSize=18, spaceAfter=30,
    )
    heading_style = ParagraphStyle(
        "PLFSHeading", parent=styles["Heading1"], fontSize=14, spaceAfter=12,
    )
    statement_style = ParagraphStyle(
        "PLFSStatement", parent=styles["Heading2"], fontSize=11,
        spaceAfter=6, spaceBefore=12,
    )
    body_style = styles["Normal"]

    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    elements = []

    # Page 1: Cover
    elements.append(Spacer(1, 40 * mm))
    elements.append(Paragraph(
        "Periodic Labour Force Survey (PLFS)", title_style
    ))
    elements.append(Paragraph(
        "Quarterly Bulletin: January-March 2024", heading_style
    ))
    elements.append(Spacer(1, 20 * mm))
    elements.append(Paragraph(
        "National Statistical Office<br/>"
        "Ministry of Statistics and Programme Implementation<br/>"
        "Government of India",
        body_style,
    ))
    elements.append(PageBreak())

    # Page 2: Chapter 2 - Key Indicators
    elements.append(Paragraph("Chapter 2: Key Labour Force Indicators", heading_style))
    elements.append(Paragraph(
        "Statement 2.1: Quarterly estimates of key labour market indicators "
        "for persons of age 15 years and above in CWS",
        statement_style,
    ))
    # Table data for Statement 2.1
    tbl_data = [
        ["Quarter", "LFPR (%)", "WPR (%)", "UR (%)"],
        ["Jan-Mar 2023", "40.2", "37.5", "6.8"],
        ["Apr-Jun 2023", "41.1", "38.2", "7.0"],
        ["Jul-Sep 2023", "41.5", "38.8", "6.5"],
        ["Oct-Dec 2023", "42.0", "39.2", "6.6"],
        ["Jan-Mar 2024", "42.3", "39.5", "6.7"],
    ]
    t = Table(tbl_data, colWidths=[100, 80, 80, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    elements.append(t)
    elements.append(PageBreak())

    # Page 3: Chapter 5 - LFPR by sex
    elements.append(Paragraph("Chapter 5: Labour Force Participation Rates", heading_style))
    elements.append(Paragraph(
        "Statement 5.2: LFPR (in %) for persons of age 15 years and above "
        "according to usual status (ps+ss) by sex",
        statement_style,
    ))
    tbl_data = [
        ["", "Rural", "Rural", "Rural", "Urban", "Urban", "Urban"],
        ["Period", "Male", "Female", "Person", "Male", "Female", "Person"],
        ["Jan-Mar 2023", "78.2", "33.5", "55.8", "73.1", "25.4", "49.5"],
        ["Apr-Jun 2023", "78.5", "34.1", "56.2", "73.5", "25.8", "49.8"],
        ["Jul-Sep 2023", "79.0", "34.8", "56.8", "74.0", "26.2", "50.2"],
        ["Oct-Dec 2023", "79.3", "35.2", "57.1", "74.2", "26.5", "50.5"],
        ["Jan-Mar 2024", "79.5", "35.5", "57.4", "74.5", "26.8", "50.8"],
    ]
    t = Table(tbl_data, colWidths=[90, 55, 55, 55, 55, 55, 55])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 1), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("SPAN", (1, 0), (3, 0)),  # "Rural" spans 3 cols
        ("SPAN", (4, 0), (6, 0)),  # "Urban" spans 3 cols
    ]))
    elements.append(t)
    elements.append(PageBreak())

    # Page 4: Chapter 4 - Distribution
    elements.append(Paragraph("Chapter 4: Employment and Unemployment", heading_style))
    elements.append(Paragraph(
        "Statement 4.1: Percentage distribution of persons by broad activity "
        "status for each sector",
        statement_style,
    ))
    tbl_data = [
        ["Activity Status", "Rural Male", "Rural Female", "Urban Male", "Urban Female"],
        ["Self-employed", "52.1", "58.3", "38.2", "42.5"],
        ["Regular wage/salaried", "14.5", "8.2", "45.3", "38.1"],
        ["Casual labour", "23.8", "17.5", "8.2", "5.3"],
        ["Not in labour force", "9.6", "16.0", "8.3", "14.1"],
    ]
    t = Table(tbl_data, colWidths=[120, 80, 80, 80, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    elements.append(t)
    elements.append(PageBreak())

    # Page 5: Chapter 7 - State-level (page-spanning table start)
    elements.append(Paragraph("Chapter 7: State-Level Estimates", heading_style))
    elements.append(Paragraph(
        "Statement 7.1: State/UT-wise LFPR for persons of age 15 years and above "
        "according to usual status (ps+ss)",
        statement_style,
    ))
    states_1 = [
        ["State/UT", "Rural Male", "Rural Female", "Urban Male", "Urban Female"],
        ["Andhra Pradesh", "76.5", "45.2", "71.3", "28.1"],
        ["Bihar", "68.2", "12.5", "65.8", "15.2"],
        ["Gujarat", "78.1", "32.8", "73.5", "22.1"],
        ["Haryana", "74.2", "22.5", "71.8", "18.5"],
        ["Karnataka", "77.8", "38.5", "74.2", "28.8"],
        ["Kerala", "72.5", "28.2", "70.1", "32.5"],
        ["Madhya Pradesh", "75.8", "28.1", "72.5", "20.2"],
        ["Maharashtra", "78.5", "42.1", "74.8", "25.5"],
        ["Rajasthan", "76.2", "35.8", "72.1", "18.8"],
        ["Tamil Nadu", "79.1", "42.5", "75.2", "32.1"],
        ["Uttar Pradesh", "72.8", "18.5", "70.2", "15.8"],
        ["West Bengal", "77.2", "22.8", "73.5", "25.2"],
    ]
    t = Table(states_1, colWidths=[100, 80, 80, 80, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    elements.append(t)
    elements.append(PageBreak())

    # Page 6: State-level continuation
    elements.append(Paragraph("Statement 7.1 (contd.)", statement_style))
    states_2 = [
        ["State/UT", "Rural Male", "Rural Female", "Urban Male", "Urban Female"],
        ["Assam", "74.5", "15.2", "71.2", "18.5"],
        ["Chhattisgarh", "76.8", "42.1", "72.5", "22.8"],
        ["Jharkhand", "72.1", "18.8", "68.5", "15.2"],
        ["Odisha", "75.2", "25.5", "72.8", "22.1"],
        ["Punjab", "76.5", "22.8", "73.8", "20.5"],
        ["Telangana", "77.1", "42.5", "73.2", "28.1"],
        ["Uttarakhand", "74.8", "28.5", "72.1", "22.5"],
        ["All India", "79.5", "35.5", "74.5", "26.8"],
    ]
    t = Table(states_2, colWidths=[100, 80, 80, 80, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    elements.append(t)

    doc.build(elements)
    return output_path


def _create_minimal_plfs_pdf(output_path: Path | None = None) -> Path:
    """Fallback: create a minimal PLFS-style PDF without reportlab."""
    try:
        from fpdf import FPDF
    except ImportError:
        # Ultra-minimal: write raw PDF bytes
        return _write_raw_plfs_pdf(output_path)

    if output_path is None:
        import tempfile
        output_path = Path(tempfile.mkdtemp()) / "plfs_synthetic.pdf"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Page 1: Cover
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 40, "", ln=True)
    pdf.cell(0, 10, "Periodic Labour Force Survey (PLFS)", ln=True, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, "Quarterly Bulletin: January-March 2024", ln=True, align="C")

    # Page 2: Statement 2.1
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, "Chapter 2: Key Labour Force Indicators", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6,
        "Statement 2.1: Quarterly estimates of key labour market indicators "
        "for persons of age 15 years and above in CWS"
    )

    # Page 3: Statement 5.2
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, "Chapter 5: Labour Force Participation Rates", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6,
        "Statement 5.2: LFPR (in %) for persons of age 15 years and above "
        "according to usual status (ps+ss) by sex"
    )

    # Page 4: Statement 4.1
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, "Chapter 4: Employment and Unemployment", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6,
        "Statement 4.1: Percentage distribution of persons by broad activity "
        "status for each sector"
    )

    # Page 5: Statement 7.1
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, "Chapter 7: State-Level Estimates", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6,
        "Statement 7.1: State/UT-wise LFPR for persons of age 15 years and above"
    )

    # Page 6: Continuation
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 10, "Statement 7.1 (contd.)", ln=True)

    pdf.output(str(output_path))
    return output_path


def _write_raw_plfs_pdf(output_path: Path | None = None) -> Path:
    """Ultra-minimal raw PDF with PLFS content (no dependencies)."""
    if output_path is None:
        import tempfile
        output_path = Path(tempfile.mkdtemp()) / "plfs_synthetic.pdf"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Multi-page minimal PDF
    pages_content = [
        "Periodic Labour Force Survey (PLFS) Quarterly Bulletin January-March 2024",
        "Statement 2.1: Quarterly estimates of key labour market indicators for persons of age 15 years and above in CWS",
        "Statement 5.2: LFPR (in %) for persons of age 15 years and above according to usual status by sex",
        "Statement 4.1: Percentage distribution of persons by broad activity status for each sector",
        "Statement 7.1: State/UT-wise LFPR for persons of age 15 years and above",
        "Statement 7.1 (contd.) Assam Bihar Chhattisgarh",
    ]

    # Build PDF structure
    objects: list[bytes] = []
    offsets: list[int] = []
    content = b""

    # Object 1: Catalog
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    # Object 2: Pages
    page_refs = " ".join(f"{i + 3} 0 R" for i in range(len(pages_content)))
    objects.append(
        f"2 0 obj\n<< /Type /Pages /Kids [{page_refs}] /Count {len(pages_content)} >>\nendobj\n".encode()
    )

    # Font object
    font_obj_num = 3 + len(pages_content) * 2
    objects.append(
        f"{font_obj_num} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n".encode()
    )

    # Page + content stream objects
    for i, text in enumerate(pages_content):
        page_obj_num = 3 + i
        stream_obj_num = 3 + len(pages_content) + i

        # Page object
        objects.append(
            f"{page_obj_num} 0 obj\n<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 595 842] "
            f"/Contents {stream_obj_num} 0 R "
            f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> >>\nendobj\n".encode()
        )

        # Content stream
        escaped_text = text.replace("(", "\\(").replace(")", "\\)")
        stream_content = f"BT /F1 10 Tf 50 780 Td ({escaped_text}) Tj ET"
        stream_bytes = stream_content.encode()
        objects.append(
            f"{stream_obj_num} 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode()
            + stream_bytes
            + b"\nendstream\nendobj\n"
        )

    # Build PDF
    pdf_bytes = b"%PDF-1.4\n"
    for obj in objects:
        offsets.append(len(pdf_bytes))
        pdf_bytes += obj

    # xref
    xref_offset = len(pdf_bytes)
    pdf_bytes += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        pdf_bytes += f"{off:010d} 00000 n \n".encode()

    pdf_bytes += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    output_path.write_bytes(pdf_bytes)
    return output_path
