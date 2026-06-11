"""Tests for report_builder.chunking SectionGraph (Phase 2)."""
import json
from pathlib import Path

import pytest

from report_builder.chunking import (
    SectionBlock,
    DocumentSectionGraph,
    build_section_graph,
    normalize_section_title,
    is_back_matter_title,
    expected_entities_for_section,
)


@pytest.fixture
def mzgho_layout():
    """Load mzgho pass1 layout regions."""
    path = Path(__file__).parent.parent / "outputs" / "mzgho" / "_pass_outputs" / "pass1_layout_regions.json"
    if not path.exists():
        pytest.skip("mzgho output not available")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def mzgho_graph(mzgho_layout):
    """Build SectionGraph from mzgho layout."""
    return build_section_graph(
        toc_entries=mzgho_layout["toc_entries"],
        layout_pages=mzgho_layout["pages"],
        doc_type="pib_press_release",
        doc_title="PLFS 2025",
    )


def test_section_graph_builds(mzgho_graph):
    assert isinstance(mzgho_graph, DocumentSectionGraph)
    assert len(mzgho_graph.sections) >= 7
    assert len(mzgho_graph.backMatter) >= 3


def test_wpr_section_exists(mzgho_graph):
    wpr_sec = mzgho_graph.section_for_page(2)
    assert wpr_sec is not None
    assert "worker population" in wpr_sec.title.lower()


def test_wpr_expected_entities(mzgho_graph):
    wpr_sec = mzgho_graph.section_for_page(2)
    assert "Worker Population Ratio" in wpr_sec.expectedEntities


def test_ur_section_exists(mzgho_graph):
    ur_sec = mzgho_graph.section_for_page(3)
    assert ur_sec is not None
    assert "unemployment" in ur_sec.title.lower()


def test_ur_expected_entities(mzgho_graph):
    ur_sec = mzgho_graph.section_for_page(3)
    assert "Unemployment Rate" in ur_sec.expectedEntities


def test_lfpr_section_exists(mzgho_graph):
    lfpr_sec = mzgho_graph.section_for_page(1)
    assert lfpr_sec is not None
    assert "labour force" in lfpr_sec.title.lower() or "lfpr" in lfpr_sec.title.lower()


def test_back_matter_detected(mzgho_graph):
    back_titles = [s.title for s in mzgho_graph.backMatter]
    assert any("sample size" in t.lower() for t in back_titles)


def test_figures_associated_to_wpr(mzgho_graph):
    wpr_sec = mzgho_graph.section_for_page(2)
    assert wpr_sec is not None
    figs = mzgho_graph.figures_for_section(wpr_sec.sectionId)
    assert len(figs) >= 1


def test_figures_associated_to_ur(mzgho_graph):
    ur_sec = mzgho_graph.section_for_page(3)
    assert ur_sec is not None
    figs = mzgho_graph.figures_for_section(ur_sec.sectionId)
    assert len(figs) >= 1


def test_normalize_section_title():
    assert normalize_section_title("2. Worker Population Ratio") == "Worker Population Ratio"
    assert normalize_section_title("A. Introduction") == "Introduction"
    assert normalize_section_title("  7 Average number  ") == "Average number"


def test_is_back_matter():
    assert is_back_matter_title("A. Introduction")
    assert is_back_matter_title("B Sample Size")
    assert is_back_matter_title("C. Changes in Sample Design of PLFS")
    assert is_back_matter_title("D Conceptual Framework of Key Indicators")
    assert not is_back_matter_title("3 Unemployment Rates (UR)")
    assert not is_back_matter_title("Worker Population Ratio")


def test_expected_entities_lfpr():
    ents = expected_entities_for_section("1 Stable Labour Force Participation Rate (LFPR)")
    assert "Labour Force Participation Rate" in ents


def test_expected_entities_earnings():
    ents = expected_entities_for_section("6 Earnings of female workers")
    assert "Average Monthly Earnings" in ents
    assert "Gender" in ents


def test_section_graph_to_dict(mzgho_graph):
    d = mzgho_graph.to_dict()
    assert d["sections"] >= 7
    assert d["backMatter"] >= 3
    assert d["figuresAssociated"] >= 6
