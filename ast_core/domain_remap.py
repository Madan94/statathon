"""Domain structure remap only — headings/lists, no data filling."""
from __future__ import annotations

from .schema import MultiAST

_HEADING_MAP: dict[str, str] = {
    "Energy Reserves and Potential": "Consumer Price Index and Inflation",
    "CHAPTER 1: Energy Reserves and Potential": "CHAPTER 1: Consumer Price Index and Inflation",
    "Global Classification of Energy Reserves": "Measurement Framework for Consumer Price Index",
    "Energy Reserves in India": "Price Movements in India",
    "1.1 Coal Reserves": "1.1 General Price Index by State",
    "1.2 Lignite Reserves": "1.2 Inflation Rate (Year-on-Year) by State",
    "1.3 Crude Oil Reserves": "1.3 All-India Linking (AL) Index — Leading States",
    "1.4 Natural Gas Reserves": "1.4 Retail (RL) Inflation — Leading States",
    "1.5 Renewable Energy Potential in India": "1.5 Inflation Distribution Across States",
    "Geographical Distribution of Renewable Energy Potential": (
        "Geographical Distribution of General Price Index"
    ),
}

_FIGURE_CAPTIONS: dict[str, str] = {
    "fig_001": "Fig 1.1: Statewise share of General Index (AL)",
    "fig_002": "Fig 1.2: Statewise year-on-year inflation (AL)",
    "fig_003": "Fig 1.3: Top states by General Index (AL)",
    "fig_004": "Fig 1.4: Top states by inflation (AL)",
    "fig_005": "Fig 1.5: Distribution of states by inflation band",
    "fig_006": "Fig 1.6: Statewise General Index (AL)",
}

_TABLE_TITLE_PREFIX = {
    "table_001": "Table 1.1: Statewise General Index and Inflation",
    "table_002": "Table 1.2: States with highest and lowest inflation",
    "table_003": "Table 1.3: All-India monthly index and inflation",
    "table_004": "Table 1.4: Top states — index and inflation summary",
}


def clear_prefilled_slots(ast: MultiAST) -> None:
    for fig in ast.figureAST.figures:
        fig.computed_chart = None
    for table in ast.tableAST.tables:
        table.rows = []
        table.columns = []


def apply_heading_remap(ast: MultiAST) -> None:
    for para in ast.contentAST.paragraphs:
        if para.content in _HEADING_MAP:
            para.content = _HEADING_MAP[para.content]
        elif para.type in ("heading_1", "heading_2", "chapter_header", "subtitle"):
            for old, new in _HEADING_MAP.items():
                if old in para.content:
                    para.content = para.content.replace(old, new)
    for fig in ast.figureAST.figures:
        if fig.figureId in _FIGURE_CAPTIONS:
            fig.caption = _FIGURE_CAPTIONS[fig.figureId]
    for table in ast.tableAST.tables:
        if table.tableId in _TABLE_TITLE_PREFIX:
            table.title = _TABLE_TITLE_PREFIX[table.tableId]
    for lst in ast.contentAST.lists:
        if lst.id == "l_001":
            lst.items = [
                "Headline index: General Index (base 2019=100).",
                "Current-linking: index_al, inflation_al.",
                "Retail-linking: index_rl, inflation_rl.",
            ]
