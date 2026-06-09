"""R1.1 gate — render layer numbers + theme foundation.

Covers value formatting (Indian/international/percent/units/empty), the theme
registry (3 presets + default), and the back-compat invariant that
``render_html`` / ``render_pdf`` stay importable from ``report_builder.generation``.
"""
from __future__ import annotations

from report_builder.generation.render.numbers import (
    EM_DASH, esc, format_value, parse_format,
)
from report_builder.generation.render.theme import (
    DEFAULT_THEME_ID, THEMES, Theme, get_theme, theme_css,
)


# ── parse_format ──────────────────────────────────────────────────────────────

def test_parse_format_tokens():
    assert parse_format("percent.1") == ("percent", 1)
    assert parse_format("percent.0") == ("percent", 0)
    assert parse_format("number.2") == ("number", 2)
    assert parse_format(None) == ("number", 1)
    assert parse_format("weird") == ("weird", 1)


# ── format_value: percent ─────────────────────────────────────────────────────

def test_percent_from_format_and_unit():
    assert format_value(56.3, fmt="percent.1") == "56.3%"
    assert format_value(56.0, fmt="percent.0") == "56%"
    assert format_value(47.1, unit="percent") == "47.1%"   # unit drives percent
    assert format_value(65.12, fmt="percent.1") == "65.1%"  # rounds


# ── format_value: Indian vs international grouping ─────────────────────────────

def test_indian_grouping_default():
    assert format_value(1234567, system="indian") == "12,34,567"
    assert format_value(100000, system="indian") == "1,00,000"
    assert format_value(999, system="indian") == "999"
    assert format_value(12345, system="indian") == "12,345"


def test_international_grouping():
    assert format_value(1234567, system="international") == "1,234,567"
    assert format_value(1000, system="international") == "1,000"


def test_decimals_and_negative():
    assert format_value(1234.5, fmt="number.1", system="indian") == "1,234.5"
    assert format_value(-1234.5, fmt="number.1", system="indian") == "-1,234.5"
    assert format_value(-5.0, fmt="percent.1") == "-5.0%"


# ── format_value: empty + non-numeric ─────────────────────────────────────────

def test_empty_and_passthrough():
    assert format_value(None) == EM_DASH
    assert format_value(None, empty="N/A") == "N/A"
    assert format_value("Himachal Pradesh") == "Himachal Pradesh"
    assert format_value(True) == "True"            # bool not treated as number


def test_unit_suffix_and_prefix():
    assert format_value(500, unit="mw", system="indian") == "500 MW"
    assert format_value(1000, unit="inr", system="international") == "\u20b91,000"


def test_esc():
    assert esc("<b>") == "&lt;b&gt;"
    assert esc(None) == ""


# ── theme registry ────────────────────────────────────────────────────────────

def test_theme_presets_present():
    assert set(THEMES) == {"mospi_navy", "mospi_saffron", "neutral_grey"}
    assert DEFAULT_THEME_ID == "mospi_navy"
    for t in THEMES.values():
        assert isinstance(t, Theme)
        assert len(t.palette) >= 4


def test_get_theme_resolution():
    assert get_theme(None).id == "mospi_navy"
    assert get_theme("neutral_grey").id == "neutral_grey"
    assert get_theme("does_not_exist").id == "mospi_navy"   # falls back
    navy = THEMES["mospi_navy"]
    assert get_theme(navy) is navy                          # passthrough


def test_theme_css_contains_palette_and_vars():
    css = theme_css("mospi_navy")
    assert "--accent:#0B5394" in css
    assert "tr.subtotal" in css            # subtotal styling present (used in R1.3)
    assert "Noto Sans Devanagari" in css   # bilingual font fallback
    saffron = theme_css("mospi_saffron")
    assert "--accent:#B45F06" in saffron


# ── back-compat invariant ─────────────────────────────────────────────────────

def test_public_api_imports_stable():
    from report_builder.generation import render_html, render_pdf  # noqa: F401
    from report_builder.generation.render import render_html as rh  # noqa: F401
    assert callable(render_html) and callable(render_pdf)
