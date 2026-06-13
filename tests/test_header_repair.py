"""P3 gate tests: multi-row header repair (D2) — flat headers + columnGroups + measures."""
from __future__ import annotations

from report_builder.extraction_pipeline import (
    _analyze_table_header,
    _detect_header_row_count,
    _merge_multirow_headers,
)

# PLFS 2-row spanning header (State + LFPR{Rural,Urban,Total} + WPR{Rural,Urban,Total}).
PLFS_2ROW = [
    ["State/UT", "LFPR", "", "", "WPR", "", ""],
    ["", "Rural", "Urban", "Total", "Rural", "Urban", "Total"],
    ["Kerala", "55.1", "52.3", "54.0", "53.1", "47.0", "50.2"],
    ["Bihar", "44.2", "41.0", "43.1", "40.0", "38.2", "39.5"],
]

# PIB-style 3-row header (Sector → Gender → leaf), the case that broke the old merge.
PIB_3ROW = [
    ["State", "Rural", "", "Urban", ""],
    ["", "Male", "Female", "Male", "Female"],
    ["", "WPR", "WPR", "WPR", "WPR"],
    ["Goa", "60.1", "30.2", "58.0", "40.4"],
]


def test_header_row_count_detection():
    assert _detect_header_row_count(PLFS_2ROW) == 2
    assert _detect_header_row_count(PIB_3ROW) == 3


def test_plfs_flat_headers_merge():
    info = _analyze_table_header(PLFS_2ROW)
    assert info["data_start"] == 2
    assert info["headers"][0] == "State/UT"
    assert "LFPR Rural" in info["headers"]
    assert "WPR Total" in info["headers"]


def test_plfs_column_groups():
    info = _analyze_table_header(PLFS_2ROW)
    labels = {g["label"] for g in info["columnGroups"]}
    assert "LFPR" in labels and "WPR" in labels
    lfpr = next(g for g in info["columnGroups"] if g["label"] == "LFPR")
    assert lfpr["span"] == 3


def test_pib_three_row_header():
    info = _analyze_table_header(PIB_3ROW)
    assert info["headerRows"] == 3
    assert info["data_start"] == 3
    # Top band "Rural" spans the two gender columns under it.
    labels = {g["label"] for g in info["columnGroups"]}
    assert "Rural" in labels and "Urban" in labels


def test_backcompat_wrapper():
    headers, data_start = _merge_multirow_headers(PLFS_2ROW)
    assert data_start == 2
    assert headers == _analyze_table_header(PLFS_2ROW)["headers"]


def test_single_row_header_unchanged():
    simple = [["State", "WPR", "LFPR"], ["Goa", "60.1", "65.0"]]
    info = _analyze_table_header(simple)
    assert info["headerRows"] == 1
    assert info["headers"] == ["State", "WPR", "LFPR"]
    assert info["columnGroups"] == []
