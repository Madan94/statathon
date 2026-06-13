"""Tests for PLFS-specific extraction features (Phase 2).

Tests:
  - PLFS glossary loading
  - Statement pattern detection
  - Statement classification into archetypes
  - Entity extraction from statement titles
  - Question generation from statements
  - Scoped dedup with PLFS entities
  - Page-spanning table merger
  - Hierarchical table model
  - VLM-Direct PLFS inferrer
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from ast_core.schema import TemplateEntity, AnswerComponent
from template_engine.vlm.schemas import VLMPageResult, VLMRegion, VLMBBox, VLMTableData


# ---------------------------------------------------------------------------
# Glossary Tests
# ---------------------------------------------------------------------------

class TestPLFSGlossary:
    """Test PLFS glossary loading and structure."""

    def test_glossary_loads(self):
        from template_engine.extraction.plfs_parser import _load_glossary
        g = _load_glossary()
        assert "abbreviations" in g
        assert "statement_archetypes" in g
        assert "column_semantics" in g
        assert "entity_hints" in g

    def test_glossary_abbreviations(self):
        from template_engine.extraction.plfs_parser import _load_glossary
        g = _load_glossary()
        abbr = g["abbreviations"]
        assert abbr["PLFS"] == "Periodic Labour Force Survey"
        assert abbr["LFPR"] == "Labour Force Participation Rate"
        assert abbr["WPR"] == "Worker Population Ratio"
        assert abbr["UR"] == "Unemployment Rate"
        assert abbr["CWS"] == "Current Weekly Status"
        assert abbr["UPSS"] == "Usual Principal and Subsidiary Status"

    def test_glossary_archetypes(self):
        from template_engine.extraction.plfs_parser import _load_glossary
        g = _load_glossary()
        archetypes = g["statement_archetypes"]
        assert "distribution" in archetypes
        assert "rate" in archetypes
        assert "trend" in archetypes
        assert "cross_tabulation" in archetypes
        assert "state_level" in archetypes

    def test_entity_hints(self):
        from template_engine.extraction.plfs_parser import _load_glossary
        g = _load_glossary()
        hints = g["entity_hints"]
        assert hints["LFPR"]["entityType"] == "measure"
        assert hints["Rural"]["entityType"] == "dimension"
        assert hints["CWS"]["entityType"] == "filter"


# ---------------------------------------------------------------------------
# Statement Detection Tests
# ---------------------------------------------------------------------------

class TestStatementDetection:
    """Test PLFS Statement pattern detection."""

    def _make_pages_with_statements(self) -> list[VLMPageResult]:
        """Create mock pages with PLFS statement text."""
        return [
            VLMPageResult(
                pageIndex=0,
                rawText="Periodic Labour Force Survey - Cover Page",
                regions=[VLMRegion(regionId="r_0_0", role="title",
                                   text="Periodic Labour Force Survey")],
            ),
            VLMPageResult(
                pageIndex=1,
                rawText="Statement 2.1: Quarterly estimates of key labour market indicators",
                regions=[
                    VLMRegion(regionId="r_1_0", role="heading_h1",
                              text="Chapter 2: Key Indicators"),
                    VLMRegion(regionId="r_1_1", role="heading_h2",
                              text="Statement 2.1: Quarterly estimates of key labour market indicators for persons of age 15 years and above in CWS"),
                ],
            ),
            VLMPageResult(
                pageIndex=2,
                rawText="Statement 5.2: LFPR (in %) for persons of age 15 years and above by sex",
                regions=[
                    VLMRegion(regionId="r_2_0", role="heading_h2",
                              text="Statement 5.2: LFPR (in %) for persons of age 15 years and above according to usual status (ps+ss) by sex"),
                ],
            ),
            VLMPageResult(
                pageIndex=3,
                rawText="Statement 4.1: Percentage distribution of persons by broad activity status",
                regions=[
                    VLMRegion(regionId="r_3_0", role="heading_h2",
                              text="Statement 4.1: Percentage distribution of persons by broad activity status for each sector"),
                ],
            ),
        ]

    def test_detects_statements(self):
        from template_engine.extraction.plfs_parser import detect_plfs_statements
        pages = self._make_pages_with_statements()
        detections = detect_plfs_statements(pages)
        assert len(detections) >= 3
        # Check statement numbers
        stmt_nums = [(d["chapter"], d["sequence"]) for d in detections]
        assert (2, 1) in stmt_nums
        assert (5, 2) in stmt_nums
        assert (4, 1) in stmt_nums

    def test_no_statements_in_non_plfs(self):
        from template_engine.extraction.plfs_parser import detect_plfs_statements
        pages = [
            VLMPageResult(pageIndex=0, rawText="Generic report without statements",
                          regions=[VLMRegion(regionId="r_0_0", role="paragraph",
                                            text="Some regular text here")]),
        ]
        detections = detect_plfs_statements(pages)
        assert len(detections) == 0

    def test_detection_includes_title(self):
        from template_engine.extraction.plfs_parser import detect_plfs_statements
        pages = self._make_pages_with_statements()
        detections = detect_plfs_statements(pages)
        d21 = next(d for d in detections if d["chapter"] == 2 and d["sequence"] == 1)
        assert "labour market indicators" in d21["title"].lower()


# ---------------------------------------------------------------------------
# Classification Tests
# ---------------------------------------------------------------------------

class TestStatementClassification:
    """Test archetype classification of statements."""

    def test_distribution_archetype(self):
        from template_engine.extraction.plfs_parser import classify_statement
        assert classify_statement("Percentage distribution of persons by broad activity status") == "distribution"

    def test_rate_archetype(self):
        from template_engine.extraction.plfs_parser import classify_statement
        assert classify_statement("LFPR (in %) for persons of age 15 years and above by sex") == "rate"

    def test_trend_archetype(self):
        from template_engine.extraction.plfs_parser import classify_statement
        assert classify_statement("Quarterly estimates of key labour indicators") == "trend"

    def test_state_level_archetype(self):
        from template_engine.extraction.plfs_parser import classify_statement
        assert classify_statement("State/UT-wise LFPR for persons of age 15 years and above") == "state_level"

    def test_cross_tabulation_archetype(self):
        from template_engine.extraction.plfs_parser import classify_statement
        assert classify_statement("Workers by industry (NIC-2008) and status in employment") == "cross_tabulation"

    def test_unknown_falls_to_descriptive(self):
        from template_engine.extraction.plfs_parser import classify_statement
        assert classify_statement("Some random title without keywords") == "descriptive"


# ---------------------------------------------------------------------------
# Entity Extraction Tests
# ---------------------------------------------------------------------------

class TestPLFSEntityExtraction:
    """Test entity extraction from PLFS statement titles."""

    def test_extracts_lfpr_entity(self):
        from template_engine.extraction.plfs_parser import extract_entities_from_statement
        entities = extract_entities_from_statement(
            "LFPR (in %) for persons of age 15 years and above by sex",
            chapter=5, sequence=2, page_index=2,
        )
        names = [e.name for e in entities]
        assert "LFPR" in names
        lfpr = next(e for e in entities if e.name == "LFPR")
        assert lfpr.entityType == "measure"
        assert lfpr.confidence >= 0.85

    def test_extracts_dimension_entities(self):
        from template_engine.extraction.plfs_parser import extract_entities_from_statement
        entities = extract_entities_from_statement(
            "LFPR for Rural and Urban sectors by Male and Female",
            chapter=5, sequence=3, page_index=3,
        )
        names = [e.name for e in entities]
        assert any("Rural" in n for n in names)

    def test_extracts_multiple_measures(self):
        from template_engine.extraction.plfs_parser import extract_entities_from_statement
        entities = extract_entities_from_statement(
            "LFPR, WPR and UR for persons by usual status (ps+ss)",
            chapter=2, sequence=1, page_index=1,
        )
        names = [e.name for e in entities]
        assert "LFPR" in names
        assert "WPR" in names
        assert "UR" in names


# ---------------------------------------------------------------------------
# Question Generation Tests
# ---------------------------------------------------------------------------

class TestPLFSQuestionGeneration:
    """Test question generation from detected statements."""

    def test_full_extraction_pipeline(self):
        from template_engine.extraction.plfs_parser import extract_plfs_questions
        from template_engine.vlm.schemas import VLMPageResult, VLMRegion

        pages = [
            VLMPageResult(
                pageIndex=0,
                rawText="Statement 2.1: Quarterly estimates of key labour indicators",
                regions=[VLMRegion(regionId="r_0_0", role="heading_h2",
                                   text="Statement 2.1: Quarterly estimates of key labour indicators")],
            ),
            VLMPageResult(
                pageIndex=1,
                rawText="Statement 5.2: LFPR by sex for age 15 and above",
                regions=[VLMRegion(regionId="r_1_0", role="heading_h2",
                                   text="Statement 5.2: LFPR by sex for age 15 and above")],
            ),
        ]

        topics, entities = extract_plfs_questions(pages)
        assert len(topics) >= 1
        assert len(entities) >= 1

        # Check questions have correct structure
        all_questions = [q for t in topics for q in t.questions]
        assert len(all_questions) >= 2
        for q in all_questions:
            assert q.questionId.startswith("q_plfs_")
            assert q.inferenceConfidence >= 0.80
            assert q.inferenceMethod == "plfs_parser"

    def test_question_has_answer_structure(self):
        from template_engine.extraction.plfs_parser import (
            statement_to_question,
            extract_entities_from_statement,
        )
        entities = extract_entities_from_statement(
            "LFPR by sex", chapter=5, sequence=2, page_index=2,
        )
        detection = {
            "chapter": 5, "sequence": 2,
            "title": "LFPR by sex",
            "page_index": 2, "qualifier": "",
        }
        q = statement_to_question(detection, entities)
        assert q.answerStructure is not None
        assert len(q.answerStructure.components) >= 2


# ---------------------------------------------------------------------------
# Page-Spanning Table Merger Tests
# ---------------------------------------------------------------------------

class TestTableMerger:
    """Test page-spanning table detection and merging."""

    def test_merges_continued_tables(self):
        from template_engine.extraction.table_merger import merge_spanning_tables

        pages = [
            VLMPageResult(
                pageIndex=0,
                regions=[
                    VLMRegion(regionId="r_0_tbl", role="table", text="Table",
                              bbox=VLMBBox(x0=50, y0=500, x1=550, y1=800)),
                ],
                tables=[VLMTableData(
                    headers=["State", "LFPR Male", "LFPR Female"],
                    rows=[["AP", "76.5", "45.2"], ["Bihar", "68.2", "12.5"]],
                    regionId="r_0_tbl",
                )],
                height=842,
            ),
            VLMPageResult(
                pageIndex=1,
                rawText="contd.",
                regions=[
                    VLMRegion(regionId="r_1_tbl", role="table", text="Table contd",
                              bbox=VLMBBox(x0=50, y0=50, x1=550, y1=300)),
                ],
                tables=[VLMTableData(
                    headers=["State", "LFPR Male", "LFPR Female"],
                    rows=[["Gujarat", "78.1", "32.8"], ["Haryana", "74.2", "22.5"]],
                    regionId="r_1_tbl",
                )],
                height=842,
            ),
        ]

        result = merge_spanning_tables(pages)
        # First page table should have 4 rows now
        assert len(result[0].tables[0].rows) == 4
        # Second page should have no tables
        assert len(result[1].tables) == 0

    def test_no_merge_when_columns_differ(self):
        from template_engine.extraction.table_merger import merge_spanning_tables

        pages = [
            VLMPageResult(
                pageIndex=0,
                regions=[VLMRegion(regionId="r_0_tbl", role="table",
                                   bbox=VLMBBox(x0=50, y0=600, x1=550, y1=800))],
                tables=[VLMTableData(headers=["A", "B"], rows=[["1", "2"]], regionId="r_0_tbl")],
                height=842,
            ),
            VLMPageResult(
                pageIndex=1,
                regions=[VLMRegion(regionId="r_1_tbl", role="table",
                                   bbox=VLMBBox(x0=50, y0=50, x1=550, y1=300))],
                tables=[VLMTableData(headers=["X", "Y", "Z", "W"], rows=[["a", "b", "c", "d"]], regionId="r_1_tbl")],
                height=842,
            ),
        ]

        result = merge_spanning_tables(pages)
        # Should NOT merge — different column count
        assert len(result[0].tables[0].rows) == 1
        assert len(result[1].tables) == 1


# ---------------------------------------------------------------------------
# Hierarchical Table Model Tests
# ---------------------------------------------------------------------------

class TestHierarchicalTable:
    """Test hierarchical table features in VLMTableData."""

    def test_multi_level_headers(self):
        tbl = VLMTableData(
            headers=["", "Male", "Female", "Male", "Female"],
            rows=[["AP", "76", "45", "71", "28"]],
            headerLevels=[
                ["", "Rural", "Rural", "Urban", "Urban"],
                ["", "Male", "Female", "Male", "Female"],
            ],
        )
        assert tbl.is_hierarchical
        flat = tbl.flat_headers
        assert "Rural / Male" in flat
        assert "Urban / Female" in flat

    def test_single_level_not_hierarchical(self):
        tbl = VLMTableData(
            headers=["State", "LFPR", "WPR"],
            rows=[["AP", "76", "72"]],
        )
        assert not tbl.is_hierarchical

    def test_header_spans_serialization(self):
        tbl = VLMTableData(
            headers=["", "Male", "Female"],
            headerLevels=[["", "Rural", "Rural"], ["", "Male", "Female"]],
            headerSpans=[[(1, 2)]],  # "Rural" spans 2 columns
            rows=[["AP", "76", "45"]],
        )
        d = tbl.to_dict()
        assert "headerSpans" in d
        restored = VLMTableData.from_dict(d)
        assert restored.headerSpans == [[(1, 2)]]

    def test_merged_cells_roundtrip(self):
        tbl = VLMTableData(
            headers=["A", "B", "C"],
            rows=[["1", "2", "3"]],
            mergedCells=[(0, 0, 2, 1)],  # row 0, col 0, spans 2 rows, 1 col
        )
        d = tbl.to_dict()
        restored = VLMTableData.from_dict(d)
        assert restored.mergedCells == [(0, 0, 2, 1)]


# ---------------------------------------------------------------------------
# VLM-Direct Inferrer Tests
# ---------------------------------------------------------------------------

class TestPLFSDirectInferrer:
    """Test the PLFSDirectInferrer in the cascade."""

    def test_detects_plfs_statement(self):
        from template_engine.inference.question_inferrer import PLFSDirectInferrer
        inferrer = PLFSDirectInferrer()

        page = VLMPageResult(pageIndex=0)
        region = VLMRegion(
            regionId="r_0_0", role="heading_h2",
            text="Statement 5.2: LFPR (in %) for persons of age 15 years and above by sex",
        )
        result = inferrer.infer(page, region, [])
        assert result is not None
        question, confidence = result
        assert confidence >= 0.85
        assert "lfpr" in question.lower()

    def test_skips_non_statement_headings(self):
        from template_engine.inference.question_inferrer import PLFSDirectInferrer
        inferrer = PLFSDirectInferrer()

        page = VLMPageResult(pageIndex=0)
        region = VLMRegion(
            regionId="r_0_0", role="heading_h2",
            text="Chapter 2: Key Labour Force Indicators",
        )
        result = inferrer.infer(page, region, [])
        assert result is None

    def test_cascade_uses_plfs_first(self):
        """Verify PLFSDirectInferrer is first in cascade and fires for statements."""
        from template_engine.inference.question_inferrer import infer_questions

        pages = [VLMPageResult(
            pageIndex=0,
            regions=[
                VLMRegion(regionId="r_0_0", role="heading_h1",
                          text="Chapter 5"),
                VLMRegion(regionId="r_0_1", role="heading_h2",
                          text="Statement 5.2: LFPR (in %) for persons of age 15 years and above by sex"),
            ],
        )]
        topics = infer_questions(pages, [])
        assert len(topics) >= 1
        # Should use plfs_direct method
        all_questions = [q for t in topics for q in t.questions]
        plfs_questions = [q for q in all_questions if q.inferenceMethod == "plfs_direct"]
        assert len(plfs_questions) >= 1
