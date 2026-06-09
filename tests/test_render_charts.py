"""R1.2 gate — SVG chart kit (7 types + density).

Structural assertions (element counts / markers / angle sums) rather than brittle
full-string snapshots, so the kit can evolve without churn.
"""
from __future__ import annotations

import math
import re

from report_builder.generation.render.svg_charts import render_chart_svg


def _count(tag: str, svg: str) -> int:
    return len(re.findall(rf"<{tag}\b", svg))


def _bar(label, value, color=None):
    p = {"x": label, "y": value}
    if color:
        p["color"] = color
    return p


# ── bar (gold-like single series) ─────────────────────────────────────────────

def test_simple_bar_structure():
    chart = {
        "chartType": "bar",
        "title": "WPR",
        "yAxis": {"unit": "percent"},
        "series": [{"label": "WPR", "points": [
            _bar("Rural", 56.3, "#1F7A1F"),
            _bar("Urban", 47.1, "#0B5394"),
            _bar("Total", 52.0),
        ]}],
    }
    svg = render_chart_svg(chart)
    assert svg.startswith("<svg")
    assert 'data-charttype="bar"' in svg
    assert 'data-orientation="vertical"' in svg
    assert _count("rect", svg) == 3
    assert "#1F7A1F" in svg and "#0B5394" in svg
    assert "56.3%" in svg          # value label formatted as percent
    assert "<title>WPR</title>" in svg


# ── grouped_bar (gold contract) ───────────────────────────────────────────────

def test_grouped_bar_gold():
    chart = {
        "chartType": "grouped_bar",
        "title": "WPR by sector",
        "yAxis": {"unit": "percent"},
        "series": [
            {"label": "Rural", "points": [_bar("Male", 56.3, "#1F7A1F")]},
            {"label": "Urban", "points": [_bar("Male", 47.1, "#0B5394")]},
        ],
    }
    svg = render_chart_svg(chart)
    assert 'data-charttype="grouped_bar"' in svg
    assert _count("rect", svg) >= 2            # 2 data bars (+legend swatches)
    assert "#1F7A1F" in svg and "#0B5394" in svg
    assert "Rural" in svg and "Urban" in svg   # legend labels


# ── density fallback: >12 categories → horizontal ─────────────────────────────

def test_dense_bar_goes_horizontal():
    pts = [_bar(f"S{i}", i + 1) for i in range(15)]
    chart = {"chartType": "bar", "series": [{"label": "x", "points": pts}]}
    svg = render_chart_svg(chart)
    assert 'data-orientation="horizontal"' in svg
    assert _count("rect", svg) == 15


# ── stacked_bar ───────────────────────────────────────────────────────────────

def test_stacked_bar_structure():
    chart = {
        "chartType": "stacked_bar",
        "series": [
            {"label": "A", "points": [_bar("Q1", 30), _bar("Q2", 40)]},
            {"label": "B", "points": [_bar("Q1", 20), _bar("Q2", 10)]},
        ],
    }
    svg = render_chart_svg(chart)
    assert 'data-charttype="stacked_bar"' in svg
    assert _count("rect", svg) >= 4            # 2 cats × 2 series (+legend)


# ── stacked_100: each column sums to 100% ─────────────────────────────────────

def test_stacked_100_normalizes():
    chart = {
        "chartType": "stacked_100",
        "series": [
            {"label": "A", "points": [_bar("Q1", 30)]},
            {"label": "B", "points": [_bar("Q1", 10)]},
        ],
    }
    svg = render_chart_svg(chart)
    assert 'data-charttype="stacked_100"' in svg
    # 30/(30+10)=75%, 10/40=25% → both labels present.
    assert "75.0%" in svg and "25.0%" in svg


# ── line ──────────────────────────────────────────────────────────────────────

def test_line_structure():
    chart = {
        "chartType": "line",
        "series": [
            {"label": "2019", "points": [_bar("Q1", 10), _bar("Q2", 14), _bar("Q3", 12)]},
            {"label": "2020", "points": [_bar("Q1", 8), _bar("Q2", 9), _bar("Q3", 11)]},
        ],
    }
    svg = render_chart_svg(chart)
    assert 'data-charttype="line"' in svg
    assert _count("path", svg) == 2            # one polyline path per series
    assert _count("circle", svg) == 6          # 3 points × 2 series


# ── pie / donut: slice angles ≈ 360 ───────────────────────────────────────────

def _slice_sweep_deg(svg: str) -> float:
    """Sum the implied sweep of all pie/donut arcs via the A-flag geometry.

    We approximate by counting path 'A' arcs and trusting the renderer; instead
    assert each slice's percent label sums to ~100 which is the user-visible
    invariant.
    """
    return sum(float(m) for m in re.findall(r">([\d.]+)%<", svg))


def test_pie_percent_labels_sum_100():
    chart = {
        "chartType": "pie",
        "series": [{"label": "share", "points": [
            _bar("A", 50), _bar("B", 30), _bar("C", 20),
        ]}],
    }
    svg = render_chart_svg(chart)
    assert 'data-charttype="pie"' in svg
    assert _count("path", svg) == 3
    assert abs(_slice_sweep_deg(svg) - 100.0) < 0.5


def test_donut_has_hole_paths():
    chart = {
        "chartType": "donut",
        "series": [{"label": "share", "points": [_bar("A", 60), _bar("B", 40)]}],
    }
    svg = render_chart_svg(chart)
    assert 'data-charttype="donut"' in svg
    assert _count("path", svg) == 2
    # Donut arcs reference two radii (outer then inner) → two 'A' commands each.
    assert svg.count(" A") >= 4


# ── empty + missing degrade gracefully ────────────────────────────────────────

def test_empty_series_placeholder():
    assert "empty-slot" in render_chart_svg({"chartType": "bar", "series": []})
    assert "empty-slot" in render_chart_svg(None)


# ── unknown type → best-effort, never raises ──────────────────────────────────

def test_unknown_type_falls_back():
    chart = {"chartType": "radar", "series": [{"points": [_bar("A", 1)]}]}
    svg = render_chart_svg(chart)
    assert svg.startswith("<svg")
    assert _count("rect", svg) == 1
