"""R1.3 gate — MoSPI table renderer.

Column-group headers, measure formatting, subtotal bolding, em-dash blanks,
footnote markers, and the repeatable-header marker for print.
"""
from __future__ import annotations

from report_builder.generation.render.tables import render_table


def _gold_wpr_table():
    return {
        "tableId": "table_wpr_state",
        "title": "WPR by State and Sector",
        "columnGroups": [
            {"groupId": "g_rural", "label": "Rural", "spanRefs": ["col_rural_person"]},
            {"groupId": "g_urban", "label": "Urban", "spanRefs": ["col_urban_person"]},
        ],
        "columns": [
            {"columnId": "col_state", "header": "State/UT", "role": "dimension",
             "align": "left", "format": None},
            {"columnId": "col_rural_person", "header": "Persons", "role": "measure",
             "group": "g_rural", "unit": "percent", "format": "percent.1"},
            {"columnId": "col_urban_person", "header": "Persons", "role": "measure",
             "group": "g_urban", "unit": "percent", "format": "percent.1"},
        ],
        "rows": [
            {"col_state": "Himachal Pradesh", "col_rural_person": 65.1,
             "col_urban_person": 54.0, "rowIds": ["r:state=HP"]},
            {"col_state": "Sikkim", "col_rural_person": 63.0,
             "col_urban_person": 58.2, "rowIds": ["r:state=SK"]},
            {"col_state": "Chhattisgarh", "col_rural_person": 62.7,
             "col_urban_person": 49.3, "rowIds": ["r:state=CG"]},
        ],
        "footnotes": [
            {"noteId": "fn_source", "text": "PLFS 2023-24 Unit-Level."},
            {"noteId": "fn_wpr", "text": "WPR on usual status (ps+ss), 15+."},
        ],
    }


# ── column groups + measure formatting ────────────────────────────────────────

def test_gold_table_groups_and_measures():
    html = render_table(_gold_wpr_table())
    assert "<caption>WPR by State and Sector</caption>" in html
    assert '<th colspan="1">Rural</th>' in html
    assert '<th colspan="1">Urban</th>' in html
    assert "Himachal Pradesh" in html
    assert "65.1%" in html and "54.0%" in html
    # measure cells are right-aligned.
    assert 'class="measure"' in html
    # thead is marked repeatable for print via CSS class on table.
    assert 'class="data-table"' in html


# ── footnotes with markers ────────────────────────────────────────────────────

def test_footnote_source_marker():
    html = render_table(_gold_wpr_table())
    assert '<span class="fn-marker">Source:</span>' in html   # fn_source → marker
    assert "PLFS 2023-24 Unit-Level." in html
    assert "WPR on usual status (ps+ss), 15+." in html


def test_footnote_no_double_marker():
    t = _gold_wpr_table()
    t["footnotes"] = [{"noteId": "fn_source", "text": "Source: already prefixed."}]
    html = render_table(t)
    # text already starts with 'Source:' → no extra marker span.
    assert "fn-marker" not in html
    assert "Source: already prefixed." in html


# ── subtotal / total rows bold (opt-in) ───────────────────────────────────────

def test_subtotal_row_via_flag():
    t = _gold_wpr_table()
    t["rows"].append({
        "col_state": "All-India", "col_rural_person": 53.4,
        "col_urban_person": 47.0, "isTotal": True, "rowIds": ["r:all"],
    })
    html = render_table(t)
    assert '<tr class="subtotal">' in html


def test_subtotal_row_via_label_matcher():
    t = _gold_wpr_table()
    # No explicit flag — first dim cell "Total" triggers the default matcher.
    t["rows"].append({
        "col_state": "Total", "col_rural_person": 53.4, "col_urban_person": 47.0,
    })
    html = render_table(t)
    assert html.count('<tr class="subtotal">') == 1


def test_no_false_subtotal_on_gold():
    # None of HP/Sikkim/Chhattisgarh should be flagged.
    html = render_table(_gold_wpr_table())
    assert '<tr class="subtotal">' not in html


# ── em-dash for blanks ────────────────────────────────────────────────────────

def test_blank_cells_become_dash():
    t = _gold_wpr_table()
    t["rows"] = [{"col_state": "Nagaland", "col_rural_person": None,
                  "col_urban_person": None, "rowIds": ["r:state=NL"]}]
    html = render_table(t)
    assert html.count("\u2014") >= 2          # both measure blanks → em-dash


# ── large table still has a single thead (repeatable) ─────────────────────────

def test_large_table_single_thead():
    t = _gold_wpr_table()
    t["rows"] = [
        {"col_state": f"State {i}", "col_rural_person": 50 + i % 10,
         "col_urban_person": 40 + i % 10, "rowIds": [f"r:{i}"]}
        for i in range(40)
    ]
    html = render_table(t)
    assert html.count("<thead>") == 1 and html.count("</thead>") == 1
    assert html.count("<tr") >= 40
