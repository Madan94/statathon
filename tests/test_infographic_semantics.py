"""Tests for Phase 3: PIB Infographic Semantics."""
import json
from pathlib import Path

import pytest

from report_builder.chart_semantic_compiler import (
    classify_pib_visual_panel,
    compile_section_graph_figures,
    PIB_VISUAL_TYPES,
    FigureSemanticModel,
)
from report_builder.chunking import build_section_graph


@pytest.fixture
def mzgho_layout():
    path = Path(__file__).parent.parent / "outputs" / "mzgho" / "_pass_outputs" / "pass1_layout_regions.json"
    if not path.exists():
        pytest.skip("mzgho output not available")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def mzgho_graph(mzgho_layout):
    return build_section_graph(
        toc_entries=mzgho_layout["toc_entries"],
        layout_pages=mzgho_layout["pages"],
        doc_type="pib_press_release",
        doc_title="PLFS 2025",
    )


@pytest.fixture
def plfs_entities():
    """Build mock entity list matching PLFS domain pack."""
    from report_builder.domain_packs.plfs_press_release import PLFS_ENTITIES
    entities = []
    for i, e in enumerate(PLFS_ENTITIES):
        entities.append({
            "entityId": f"ent_{i+1:03d}",
            "canonicalName": e["name"],
            "entityType": e["entityType"],
            "aliases": e.get("aliases", []),
            "unit": e.get("unit"),
        })
    return entities


def test_classify_wpr_section():
    """WPR section figures should be metric_card_panel."""
    from report_builder.chunking import SectionBlock
    sec = SectionBlock(
        sectionId="sg_03", title="2 Worker Population Ratio (WPR)",
        pageStart=2, pageEnd=2, level=1,
        expectedEntities=["Worker Population Ratio", "Gender", "Sector"],
    )
    chart_type, conf, ents = classify_pib_visual_panel({}, section=sec)
    assert chart_type == "metric_card_panel"
    assert conf >= 0.65
    assert "Worker Population Ratio" in ents


def test_classify_ur_section():
    """UR section figures should be metric_card_panel."""
    from report_builder.chunking import SectionBlock
    sec = SectionBlock(
        sectionId="sg_04", title="3 Unemployment Rates (UR)",
        pageStart=3, pageEnd=3, level=1,
        expectedEntities=["Unemployment Rate", "Gender", "Sector"],
    )
    chart_type, conf, ents = classify_pib_visual_panel({}, section=sec)
    assert chart_type == "metric_card_panel"
    assert conf >= 0.65


def test_classify_employment_section():
    """Employment status section → infographic_panel."""
    from report_builder.chunking import SectionBlock
    sec = SectionBlock(
        sectionId="sg_05", title="4 Increase in proportion of workers with regular wage",
        pageStart=4, pageEnd=4, level=1,
        expectedEntities=["Worker Share", "Employment Status", "Gender"],
    )
    chart_type, conf, ents = classify_pib_visual_panel({}, section=sec)
    assert chart_type == "infographic_panel"
    assert conf >= 0.60


def test_classify_industry_section():
    """Industry section → infographic_panel."""
    from report_builder.chunking import SectionBlock
    sec = SectionBlock(
        sectionId="sg_06", title="5 Manufacturing and service sectors",
        pageStart=5, pageEnd=5, level=1,
        expectedEntities=["Worker Share", "Industry", "Gender"],
    )
    chart_type, conf, ents = classify_pib_visual_panel({}, section=sec)
    assert chart_type == "infographic_panel"
    assert conf >= 0.60


def test_classify_back_matter():
    """BackMatter figures → visual_summary."""
    from report_builder.chunking import SectionBlock
    sec = SectionBlock(
        sectionId="sg_10", title="A. Introduction",
        pageStart=7, pageEnd=7, level=2,
        isBackMatter=True,
    )
    chart_type, conf, ents = classify_pib_visual_panel({}, section=sec)
    assert chart_type == "visual_summary"
    assert conf <= 0.55


def test_compile_section_graph_figures(mzgho_graph, plfs_entities):
    """SectionGraph figures compile with entity links."""
    result = compile_section_graph_figures(mzgho_graph, entities=plfs_entities, doc_type="pib_press_release")
    assert len(result.figures) >= 6
    assert result.counts["pib_panels"] >= 5


def test_wpr_figure_links_to_wpr_entity(mzgho_graph, plfs_entities):
    """WPR section figure should link to WPR measure entity."""
    result = compile_section_graph_figures(mzgho_graph, entities=plfs_entities, doc_type="pib_press_release")
    # Find figures from WPR section
    wpr_figs = [f for f in result.figures if f.sectionRef and "02" in f.sectionRef or "03" in (f.sectionRef or "")]
    # At least one figure should have WPR in measureRefs
    wpr_entity_id = next((e["entityId"] for e in plfs_entities if "Worker Population" in e["canonicalName"]), None)
    assert wpr_entity_id is not None
    has_wpr_link = any(wpr_entity_id in f.measureRefs for f in result.figures)
    assert has_wpr_link, f"No figure links to WPR entity {wpr_entity_id}"


def test_no_numeric_values_in_figure_templates(mzgho_graph, plfs_entities):
    """Figure templates must be value-free."""
    import re
    result = compile_section_graph_figures(mzgho_graph, entities=plfs_entities, doc_type="pib_press_release")
    for fig in result.figures:
        assert not re.search(r'\d{3,}', fig.captionTemplate), f"Data value in caption: {fig.captionTemplate}"
        assert not re.search(r'\d+\.\d+%', fig.chartSubject), f"Percentage in subject: {fig.chartSubject}"


def test_figures_have_valid_chart_types(mzgho_graph, plfs_entities):
    """All figures should have known chart types (not just 'unknown')."""
    from report_builder.chart_semantic_compiler import ALL_CHART_TYPES
    result = compile_section_graph_figures(mzgho_graph, entities=plfs_entities, doc_type="pib_press_release")
    for fig in result.figures:
        assert fig.chartType in ALL_CHART_TYPES, f"Invalid type: {fig.chartType}"
    # Majority should NOT be 'unknown'
    unknown_count = sum(1 for f in result.figures if f.chartType == "unknown")
    assert unknown_count < len(result.figures) * 0.3, "Too many unknown figures"
