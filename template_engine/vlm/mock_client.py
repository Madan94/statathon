"""Mock VLM Client — returns pre-annotated fixtures for development without GPU.

Fixtures are loaded from test_data/sample_templates/fixtures/ directory.
Each fixture is a JSON file matching the VLMPageResult schema.

If no fixture matches the input PDF, generates a synthetic mock response
based on the filename and basic PDF metadata (page count via pdfplumber/fitz).
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from template_engine.vlm.client import VLMClient, VLMExtractionError
from template_engine.vlm.schemas import (
    VLMBBox,
    VLMChartData,
    VLMEntity,
    VLMPageResult,
    VLMRegion,
    VLMTableData,
)

logger = logging.getLogger(__name__)

# Default fixture directory
_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "test_data" / "sample_templates" / "fixtures"


class MockVLMClient(VLMClient):
    """Mock VLM backend for development — no GPU required.

    Resolution order:
      1. Look for fixture file matching PDF hash (sha256[:12].json)
      2. Look for fixture file matching PDF filename (stem.json)
      3. Generate synthetic mock based on PDF metadata
    """

    def __init__(self, fixture_dir: Path | str | None = None):
        self._fixture_dir = Path(fixture_dir) if fixture_dir else _FIXTURE_DIR

    @property
    def backend_name(self) -> str:
        return "mock"

    def health_check(self) -> bool:
        return True  # always available

    def extract_pages(self, pdf_path: Path) -> list[VLMPageResult]:
        """Load fixture or generate synthetic mock."""
        pdf_path = Path(pdf_path)  # Ensure Path object
        # Try fixture by hash
        if pdf_path.exists():
            file_hash = self._hash_file(pdf_path)[:12]
            fixture = self._fixture_dir / f"{file_hash}.json"
            if fixture.exists():
                logger.info("Mock VLM: loading hash fixture %s", fixture.name)
                return self._load_fixture(fixture)

        # Try fixture by filename
        fixture = self._fixture_dir / f"{pdf_path.stem}.json"
        if fixture.exists():
            logger.info("Mock VLM: loading name fixture %s", fixture.name)
            return self._load_fixture(fixture)

        # Generate synthetic
        logger.info("Mock VLM: generating synthetic for %s", pdf_path.name)
        return self._generate_synthetic(pdf_path)

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(131072), b""):
                h.update(chunk)
        return h.hexdigest()

    def _load_fixture(self, fixture_path: Path) -> list[VLMPageResult]:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        pages_raw = data if isinstance(data, list) else data.get("pages", [data])
        return [VLMPageResult.from_dict(p) for p in pages_raw]

    def _generate_synthetic(self, pdf_path: Path) -> list[VLMPageResult]:
        """Generate a realistic multi-page mock based on a standard MoSPI report structure."""
        page_count = self._detect_page_count(pdf_path)
        stem = pdf_path.stem.replace("_", " ").replace("-", " ").title()

        pages: list[VLMPageResult] = []

        # Page 0: Cover page
        pages.append(self._mock_cover_page(stem))

        # Page 1: Executive Summary with metrics
        if page_count > 1:
            pages.append(self._mock_executive_summary(stem))

        # Page 2: Methodology with formula
        if page_count > 2:
            pages.append(self._mock_methodology_page())

        # Page 3: Data table page
        if page_count > 3:
            pages.append(self._mock_table_page())

        # Page 4: Chart page
        if page_count > 4:
            pages.append(self._mock_chart_page())

        # Page 5+: findings/narrative
        for i in range(5, min(page_count, 8)):
            pages.append(self._mock_findings_page(i))

        return pages

    def _detect_page_count(self, pdf_path: Path) -> int:
        """Try to detect page count without heavy parsing."""
        if not pdf_path.exists():
            return 6  # default mock

        try:
            import pdfplumber
            with pdfplumber.open(str(pdf_path)) as pdf:
                return len(pdf.pages)
        except Exception:
            pass

        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            count = len(doc)
            doc.close()
            return count
        except Exception:
            pass

        return 6

    def _mock_cover_page(self, title: str) -> VLMPageResult:
        return VLMPageResult(
            pageIndex=0,
            width=595.0,
            height=842.0,
            regions=[
                VLMRegion(regionId="r_0_1", role="title", text=title,
                          bbox=VLMBBox(x0=100, y0=200, x1=495, y1=260),
                          confidence=0.95),
                VLMRegion(regionId="r_0_2", role="paragraph",
                          text="Ministry of Statistics and Programme Implementation",
                          bbox=VLMBBox(x0=150, y0=300, x1=445, y1=330),
                          confidence=0.92),
                VLMRegion(regionId="r_0_3", role="paragraph",
                          text="Government of India",
                          bbox=VLMBBox(x0=200, y0=340, x1=395, y1=360),
                          confidence=0.92),
            ],
            entities=[],
            tables=[],
            charts=[],
            rawText=f"{title}\nMinistry of Statistics and Programme Implementation\nGovernment of India",
            confidence=0.93,
        )

    def _mock_executive_summary(self, title: str) -> VLMPageResult:
        return VLMPageResult(
            pageIndex=1,
            width=595.0,
            height=842.0,
            regions=[
                VLMRegion(regionId="r_1_1", role="heading_h1",
                          text="Executive Summary",
                          bbox=VLMBBox(x0=50, y0=50, x1=300, y1=75),
                          confidence=0.97),
                VLMRegion(regionId="r_1_2", role="paragraph",
                          text="This report presents findings from the national sample survey covering household consumption expenditure across rural and urban areas.",
                          bbox=VLMBBox(x0=50, y0=85, x1=545, y1=160),
                          confidence=0.90),
                VLMRegion(regionId="r_1_3", role="heading_h2",
                          text="Key Indicators",
                          bbox=VLMBBox(x0=50, y0=180, x1=250, y1=200),
                          confidence=0.95),
                VLMRegion(regionId="r_1_4", role="paragraph",
                          text="Total households surveyed: 1,13,823. Average MPCE (Rural): ₹2,008. Average MPCE (Urban): ₹3,877.",
                          bbox=VLMBBox(x0=50, y0=210, x1=545, y1=270),
                          confidence=0.88),
            ],
            entities=[
                VLMEntity(name="Households Surveyed", entityType="measure",
                          sourceType="narrative_term", sourceRegion="r_1_4",
                          confidence=0.85, context="Total households surveyed: 1,13,823"),
                VLMEntity(name="MPCE", entityType="measure",
                          sourceType="narrative_term", sourceRegion="r_1_4",
                          confidence=0.90, context="Average MPCE (Rural): ₹2,008"),
                VLMEntity(name="Rural", entityType="dimension",
                          sourceType="narrative_term", sourceRegion="r_1_4",
                          confidence=0.88, context="MPCE (Rural)"),
                VLMEntity(name="Urban", entityType="dimension",
                          sourceType="narrative_term", sourceRegion="r_1_4",
                          confidence=0.88, context="MPCE (Urban)"),
            ],
            tables=[],
            charts=[],
            rawText="Executive Summary\nThis report presents findings...",
            confidence=0.92,
        )

    def _mock_methodology_page(self) -> VLMPageResult:
        return VLMPageResult(
            pageIndex=2,
            width=595.0,
            height=842.0,
            regions=[
                VLMRegion(regionId="r_2_1", role="heading_h1",
                          text="Methodology",
                          bbox=VLMBBox(x0=50, y0=50, x1=250, y1=75),
                          confidence=0.96),
                VLMRegion(regionId="r_2_2", role="paragraph",
                          text="A stratified multi-stage sampling design was adopted. First Stage Units (FSUs) were census villages in rural areas and Urban Frame Survey blocks in urban areas.",
                          bbox=VLMBBox(x0=50, y0=85, x1=545, y1=180),
                          confidence=0.89),
                VLMRegion(regionId="r_2_3", role="formula",
                          text="n_h = N_h × (S_h / C_h) / Σ(N_i × S_i / C_i) × n",
                          bbox=VLMBBox(x0=100, y0=200, x1=495, y1=240),
                          confidence=0.82),
                VLMRegion(regionId="r_2_4", role="paragraph",
                          text="Where n_h is the sample size for stratum h, N_h is the population, S_h is the standard deviation, and C_h is the cost per unit.",
                          bbox=VLMBBox(x0=50, y0=250, x1=545, y1=320),
                          confidence=0.87),
            ],
            entities=[
                VLMEntity(name="FSU", entityType="dimension",
                          sourceType="narrative_term", sourceRegion="r_2_2",
                          confidence=0.84, context="First Stage Units"),
                VLMEntity(name="Sample Size", entityType="measure",
                          sourceType="formula_variable", sourceRegion="r_2_3",
                          confidence=0.80, context="n_h is the sample size"),
            ],
            tables=[],
            charts=[],
            rawText="Methodology\nA stratified multi-stage sampling...",
            confidence=0.88,
        )

    def _mock_table_page(self) -> VLMPageResult:
        return VLMPageResult(
            pageIndex=3,
            width=595.0,
            height=842.0,
            regions=[
                VLMRegion(regionId="r_3_1", role="heading_h1",
                          text="Household Consumption Expenditure by State",
                          bbox=VLMBBox(x0=50, y0=50, x1=450, y1=75),
                          confidence=0.95),
                VLMRegion(regionId="r_3_2", role="table",
                          text="Table 3.1: Average MPCE by State and Sector",
                          bbox=VLMBBox(x0=50, y0=85, x1=545, y1=500),
                          confidence=0.91),
                VLMRegion(regionId="r_3_3", role="footnote",
                          text="Source: NSSO 68th Round, Schedule 1.0",
                          bbox=VLMBBox(x0=50, y0=510, x1=350, y1=530),
                          confidence=0.88),
            ],
            entities=[
                VLMEntity(name="State", entityType="dimension",
                          sourceType="table_header", sourceRegion="r_3_2",
                          confidence=0.96, context="Average MPCE by State"),
                VLMEntity(name="MPCE", entityType="measure",
                          sourceType="table_header", sourceRegion="r_3_2",
                          confidence=0.95, context="Average MPCE"),
                VLMEntity(name="Sector", entityType="dimension",
                          sourceType="table_header", sourceRegion="r_3_2",
                          confidence=0.94, context="State and Sector"),
            ],
            tables=[
                VLMTableData(
                    headers=["State", "Rural MPCE (₹)", "Urban MPCE (₹)", "Combined MPCE (₹)"],
                    rows=[
                        ["Andhra Pradesh", "1,847", "3,250", "2,340"],
                        ["Bihar", "1,127", "2,118", "1,319"],
                        ["Delhi", "—", "4,481", "4,481"],
                        ["Gujarat", "1,883", "3,407", "2,547"],
                        ["Karnataka", "1,791", "3,558", "2,541"],
                        ["Kerala", "2,669", "3,408", "2,997"],
                        ["Maharashtra", "1,771", "3,810", "2,712"],
                        ["Tamil Nadu", "2,078", "3,143", "2,619"],
                        ["Uttar Pradesh", "1,420", "2,379", "1,672"],
                        ["West Bengal", "1,573", "2,948", "1,946"],
                    ],
                    regionId="r_3_2",
                ),
            ],
            charts=[],
            rawText="Household Consumption Expenditure by State\nTable 3.1...",
            confidence=0.93,
        )

    def _mock_chart_page(self) -> VLMPageResult:
        return VLMPageResult(
            pageIndex=4,
            width=595.0,
            height=842.0,
            regions=[
                VLMRegion(regionId="r_4_1", role="heading_h1",
                          text="Rural vs Urban Expenditure Distribution",
                          bbox=VLMBBox(x0=50, y0=50, x1=480, y1=75),
                          confidence=0.94),
                VLMRegion(regionId="r_4_2", role="chart",
                          text="Figure 4.1: Grouped Bar Chart - MPCE by State",
                          bbox=VLMBBox(x0=50, y0=85, x1=545, y1=450),
                          confidence=0.89),
                VLMRegion(regionId="r_4_3", role="axis_label",
                          text="State",
                          bbox=VLMBBox(x0=250, y0=460, x1=340, y1=480),
                          confidence=0.92),
                VLMRegion(regionId="r_4_4", role="axis_label",
                          text="MPCE (₹)",
                          bbox=VLMBBox(x0=20, y0=250, x1=45, y1=300),
                          confidence=0.90),
                VLMRegion(regionId="r_4_5", role="legend",
                          text="Rural  Urban",
                          bbox=VLMBBox(x0=400, y0=460, x1=545, y1=480),
                          confidence=0.88),
                VLMRegion(regionId="r_4_6", role="paragraph",
                          text="The chart shows significant variation in monthly per capita expenditure across states, with urban areas consistently showing higher consumption.",
                          bbox=VLMBBox(x0=50, y0=490, x1=545, y1=560),
                          confidence=0.87),
            ],
            entities=[
                VLMEntity(name="State", entityType="dimension",
                          sourceType="chart_axis", sourceRegion="r_4_3",
                          confidence=0.92, context="x-axis label"),
                VLMEntity(name="MPCE", entityType="measure",
                          sourceType="chart_axis", sourceRegion="r_4_4",
                          confidence=0.90, context="y-axis: MPCE (₹)"),
                VLMEntity(name="Rural", entityType="dimension",
                          sourceType="chart_legend", sourceRegion="r_4_5",
                          confidence=0.88, context="Legend: Rural"),
                VLMEntity(name="Urban", entityType="dimension",
                          sourceType="chart_legend", sourceRegion="r_4_5",
                          confidence=0.88, context="Legend: Urban"),
            ],
            tables=[],
            charts=[
                VLMChartData(
                    chartType="grouped_bar",
                    title="MPCE by State",
                    xAxis="State",
                    yAxis="MPCE (₹)",
                    legendItems=["Rural", "Urban"],
                    regionId="r_4_2",
                ),
            ],
            rawText="Rural vs Urban Expenditure Distribution\nFigure 4.1...",
            confidence=0.90,
        )

    def _mock_findings_page(self, page_index: int) -> VLMPageResult:
        return VLMPageResult(
            pageIndex=page_index,
            width=595.0,
            height=842.0,
            regions=[
                VLMRegion(regionId=f"r_{page_index}_1", role="heading_h1",
                          text=f"Key Findings - Section {page_index - 4}",
                          bbox=VLMBBox(x0=50, y0=50, x1=400, y1=75),
                          confidence=0.93),
                VLMRegion(regionId=f"r_{page_index}_2", role="paragraph",
                          text="The analysis reveals statistically significant differences in consumption patterns between rural and urban households across all major expenditure categories.",
                          bbox=VLMBBox(x0=50, y0=85, x1=545, y1=180),
                          confidence=0.86),
            ],
            entities=[],
            tables=[],
            charts=[],
            rawText=f"Key Findings - Section {page_index - 4}\nThe analysis reveals...",
            confidence=0.89,
        )
