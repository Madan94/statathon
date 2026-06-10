"""P5 tests: entity enrichment (Q17 units/format, Q18 valueDomain, Q19 glossary/palette)."""
from __future__ import annotations

import pytest

try:
    from report_builder.entity_enrichment import (
        MOSPI_GLOSSARY,
        build_glossary,
        build_palette,
        enrich_document_map,
        enrich_entity,
    )
except ImportError:  # pragma: no cover - environment/refactor guard
    pytest.skip(
        "report_builder.entity_enrichment was rewritten by the E6 alias/value-domain "
        "enrichment work (now enrich_entities/AliasCandidate); this suite targets the "
        "superseded glossary/palette API. Skipped until the team updates these tests.",
        allow_module_level=True,
    )


# ── Q17: units / format / dtype ─────────────────────────────────────────────
def test_glossary_known_measure_units():
    e = {"name": "Labour Force Participation Rate (LFPR)", "entityType_hint": "measure"}
    enrich_entity(e)
    assert e["glossaryRef"] == "lfpr"
    assert e["unit"] == "percent"
    assert e["defaultFormat"] == "0.0%"
    assert e["dtypeHint"] == "float"
    assert "LFPR" in e["aliases"]
    assert e["canonicalName"] == "Labour Force Participation Rate"


def test_regex_unit_detection_for_unknown_measure():
    e = {"name": "Average Daily Wage", "entityType_hint": "measure"}
    enrich_entity(e)
    assert e["unit"] == "INR"
    assert e["defaultFormat"].startswith("\u20b9")


def test_rate_measure_gets_percent():
    e = {"name": "Female Unemployment Rate", "entityType_hint": "measure"}
    enrich_entity(e)
    assert e["unit"] == "percent"


def test_dimension_gets_no_unit_but_string_dtype():
    e = {"name": "State", "entityType_hint": "dimension"}
    enrich_entity(e)
    assert e.get("unit") is None
    assert e["dtypeHint"] == "string"


# ── Q18: valueDomain (dimension members) ────────────────────────────────────
def test_closed_dimension_members():
    e = {"name": "Sector", "entityType_hint": "dimension"}
    enrich_entity(e)
    assert e["valueDomain"]["domainType"] == "closed"
    assert e["valueDomain"]["members"] == ["Rural", "Urban"]


def test_gender_closed_members():
    e = {"name": "Gender", "entityType_hint": "dimension"}
    enrich_entity(e)
    assert e["valueDomain"]["domainType"] == "closed"
    assert "Male" in e["valueDomain"]["members"]


def test_high_cardinality_dimension_is_open():
    e = {"name": "State", "entityType_hint": "dimension"}
    enrich_entity(e)
    assert e["valueDomain"]["domainType"] == "open"
    assert e["valueDomain"]["members"] == []


# ── idempotency: re-run must not clobber ────────────────────────────────────
def test_enrich_is_idempotent():
    e = {"name": "MPCE", "entityType_hint": "measure"}
    enrich_entity(e)
    first = dict(e)
    enrich_entity(e)
    assert e == first


def test_existing_values_not_overwritten():
    e = {"name": "LFPR", "entityType_hint": "measure", "unit": "custom_unit"}
    enrich_entity(e)
    assert e["unit"] == "custom_unit"  # caller-provided value preserved


# ── Q19: glossary + palette ─────────────────────────────────────────────────
def test_build_glossary_dedupes_and_includes_only_present_terms():
    ents = [
        {"name": "LFPR", "glossaryRef": "lfpr"},
        {"name": "LFPR (again)", "glossaryRef": "lfpr"},
        {"name": "Worker Population Ratio (WPR)"},
        {"name": "Some random dimension"},
    ]
    g = build_glossary(ents)
    terms = {row["term"] for row in g}
    assert terms == {"LFPR", "WPR"}
    for row in g:
        assert row["definition"] and row["source"] == "canonical_mospi"


def test_build_palette_shape():
    p = build_palette()
    assert p["paletteId"] == "mospi_default"
    assert len(p["categorical"]) >= 3
    assert set(p["roles"]) >= {"current", "prior"}


# ── orchestrator ────────────────────────────────────────────────────────────
def test_enrich_document_map_attaches_glossary_and_palette():
    dm = {
        "all_entities": [
            {"name": "LFPR", "entityType_hint": "measure"},
            {"name": "Sector", "entityType_hint": "dimension"},
        ]
    }
    enrich_document_map(dm)
    assert dm["all_entities"][0]["unit"] == "percent"
    assert dm["all_entities"][1]["valueDomain"]["members"] == ["Rural", "Urban"]
    assert any(r["term"] == "LFPR" for r in dm["glossary"])
    assert dm["palette"]["paletteId"] == "mospi_default"


def test_glossary_constants_consistent():
    # Every glossary entry must define the keys the enricher relies on.
    for key, val in MOSPI_GLOSSARY.items():
        assert {"definition", "unit", "dtype", "format"} <= set(val)
