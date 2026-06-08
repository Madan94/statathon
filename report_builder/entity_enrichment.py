"""Entity enrichment (migration plan P5 / pass 2.7 / loop decisions Q16-Q19).

Pure, deterministic enrichment of typed entities into template-ready descriptors:

* ``enrich_entity``        \u2014 per-entity: canonicalName, aliases, unit, dtypeHint,
                             defaultFormat, valueDomain, glossaryRef (Q17/Q18).
* ``build_glossary``       \u2014 canonical MoSPI glossary + per-doc terms (Q19).
* ``build_palette``        \u2014 canonical MoSPI palette registry (Q19).
* ``enrich_document_map``  \u2014 orchestrator: enriches all_entities in place and
                             attaches ``glossary`` + ``palette`` to the map.

Layered strategy (Q17): regex + canonical glossary first; a VLM fallback is left
to the caller (the pipeline) for anything still unknown \u2014 this module never calls
an LLM or touches disk.
"""
from __future__ import annotations

import re
from typing import Any

# ── Canonical MoSPI glossary (Q19): term \u2192 {definition, unit, dtype, format} ──
# Value-free schema metadata only \u2014 no measured numbers.
MOSPI_GLOSSARY: dict[str, dict[str, Any]] = {
    "lfpr": {"definition": "Labour Force Participation Rate \u2014 share of population in the labour force.",
             "unit": "percent", "dtype": "float", "format": "0.0%"},
    "wpr": {"definition": "Worker Population Ratio \u2014 share of population employed.",
            "unit": "percent", "dtype": "float", "format": "0.0%"},
    "ur": {"definition": "Unemployment Rate \u2014 share of labour force that is unemployed.",
           "unit": "percent", "dtype": "float", "format": "0.0%"},
    "mpce": {"definition": "Monthly Per Capita Consumption Expenditure.",
             "unit": "INR", "dtype": "float", "format": "\u20b9#,##,##0"},
    "cpi": {"definition": "Consumer Price Index.", "unit": "index", "dtype": "float", "format": "0.0"},
    "gdp": {"definition": "Gross Domestic Product.", "unit": "INR_crore", "dtype": "float", "format": "\u20b9#,##,##0"},
    "gva": {"definition": "Gross Value Added.", "unit": "INR_crore", "dtype": "float", "format": "\u20b9#,##,##0"},
    "gsdp": {"definition": "Gross State Domestic Product.", "unit": "INR_crore", "dtype": "float", "format": "\u20b9#,##,##0"},
}

# ── Canonical dimension members (Q18): closed low-cardinality enums ──
# High-cardinality dims (State, District) are left OPEN (members=[], domainType=open).
CANONICAL_DIM_MEMBERS: dict[str, list[str]] = {
    "sector": ["Rural", "Urban"],
    "gender": ["Male", "Female", "Transgender"],
    "sex": ["Male", "Female", "Transgender"],
    "area": ["Rural", "Urban"],
}
_OPEN_DIMENSIONS: frozenset[str] = frozenset({
    "state", "district", "region", "city", "village", "block", "industry",
    "occupation", "year", "quarter", "month", "round",
})

# ── Unit detection (Q17): layered regex over the entity name ──
_UNIT_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(rate|ratio|percent|share|proportion)\b|%", re.I), "percent", "0.0%"),
    (re.compile(r"\b(index)\b", re.I), "index", "0.0"),
    (re.compile(r"\u20b9|\b(rupees?|inr|wage|salary|earnings?|expenditure|income|mpce)\b", re.I),
     "INR", "\u20b9#,##,##0"),
    (re.compile(r"\b(crore|lakh)\b", re.I), "INR_crore", "\u20b9#,##,##0"),
    (re.compile(r"\b(tonnes?|kg|kilograms?|quintal)\b", re.I), "tonnes", "#,##0.0"),
    (re.compile(r"\b(mw|megawatt|gw|kwh)\b", re.I), "MW", "#,##0"),
    (re.compile(r"\b(count|number|total|persons?|workers?|population)\b", re.I), "count", "#,##,##0"),
    (re.compile(r"\b(years?)\b", re.I), "years", "0.0"),
]

_ABBREV_RE = re.compile(r"\(([A-Z][A-Za-z0-9\+\-]{1,12})\)")


def _strip_parenthetical(name: str) -> str:
    bare = re.sub(r"\([^)]*\)", "", name)
    return re.sub(r"\s+", " ", bare).strip().rstrip("- ").strip()


def _glossary_key(name: str) -> str | None:
    """Match an entity name to a canonical glossary key via abbreviation or token."""
    low = name.lower()
    for m in _ABBREV_RE.finditer(name):
        if m.group(1).lower() in MOSPI_GLOSSARY:
            return m.group(1).lower()
    for key in MOSPI_GLOSSARY:
        if re.search(rf"\b{re.escape(key)}\b", low):
            return key
    return None


def _detect_unit_format(name: str, etype: str) -> tuple[str | None, str | None]:
    if etype != "measure":
        return None, None
    for rx, unit, fmt in _UNIT_RULES:
        if rx.search(name):
            return unit, fmt
    return None, None


def _value_domain(name: str, etype: str) -> dict[str, Any] | None:
    """Q18: dimension members \u2014 canonical closed enum, or open for high-cardinality."""
    if etype not in ("dimension", "filter"):
        return None
    low = name.lower()
    for key, members in CANONICAL_DIM_MEMBERS.items():
        if re.search(rf"\b{re.escape(key)}\b", low):
            return {"domainType": "closed", "members": list(members)}
    for key in _OPEN_DIMENSIONS:
        if re.search(rf"\b{re.escape(key)}\b", low):
            return {"domainType": "open", "members": []}
    return {"domainType": "open", "members": []}


def enrich_entity(entity: dict[str, Any]) -> dict[str, Any]:
    """Enrich a single typed entity in place with template descriptors (Q17/Q18/Q19).

    Idempotent: re-running does not clobber values already present.
    """
    name = entity.get("name") or ""
    etype = entity.get("entityType_hint") or entity.get("entityType") or "dimension"

    # canonicalName + aliases
    bare = _strip_parenthetical(name)
    entity.setdefault("canonicalName", bare or name)
    aliases = list(entity.get("aliases") or [])
    for m in _ABBREV_RE.finditer(name):
        if m.group(1) not in aliases and m.group(1) != name:
            aliases.append(m.group(1))
    if bare and bare != name and len(bare) >= 4 and bare not in aliases:
        aliases.append(bare)
    entity["aliases"] = aliases

    # glossary link
    gkey = _glossary_key(name)
    if gkey and not entity.get("glossaryRef"):
        entity["glossaryRef"] = gkey

    # unit + format (glossary first, then regex)
    if not entity.get("unit") or not entity.get("defaultFormat"):
        g = MOSPI_GLOSSARY.get(gkey or "")
        if g:
            entity.setdefault("unit", g["unit"])
            entity.setdefault("defaultFormat", g["format"])
            entity.setdefault("dtypeHint", g["dtype"])
        else:
            unit, fmt = _detect_unit_format(name, etype)
            if unit:
                entity.setdefault("unit", unit)
                entity.setdefault("defaultFormat", fmt)

    # dtype hint backstop
    if not entity.get("dtypeHint"):
        entity["dtypeHint"] = "float" if etype == "measure" else "string"

    # valueDomain (dimension members)
    vd = _value_domain(name, etype)
    if vd is not None and not entity.get("valueDomain"):
        entity["valueDomain"] = vd

    return entity


def build_glossary(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Q19: canonical MoSPI glossary terms that appear in this document, deduped."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for e in entities or []:
        gkey = e.get("glossaryRef") or _glossary_key(e.get("name") or "")
        if gkey and gkey in MOSPI_GLOSSARY and gkey not in seen:
            seen.add(gkey)
            g = MOSPI_GLOSSARY[gkey]
            out.append({
                "term": gkey.upper(),
                "definition": g["definition"],
                "unit": g["unit"],
                "format": g["format"],
                "source": "canonical_mospi",
            })
    return out


def build_palette() -> dict[str, Any]:
    """Q19: canonical MoSPI palette registry (value-free; doc overrides applied by caller)."""
    return {
        "paletteId": "mospi_default",
        "source": "canonical_mospi",
        "categorical": ["#1F4E79", "#C55A11", "#548235", "#7030A0", "#BF9000", "#2E75B6"],
        "sequential": ["#DEEBF7", "#9ECAE1", "#4292C6", "#08519C"],
        "diverging": ["#C55A11", "#F4B183", "#FFFFFF", "#9DC3E6", "#1F4E79"],
        "roles": {"current": "#1F4E79", "prior": "#9DC3E6", "delta_up": "#548235", "delta_down": "#C55A11"},
    }


def enrich_document_map(document_map: dict[str, Any]) -> dict[str, Any]:
    """Pass 2.7 orchestrator (Q16): enrich all_entities + attach glossary & palette.

    Pure + deterministic. Returns the same map (mutated in place).
    """
    entities = document_map.get("all_entities") or []
    for e in entities:
        enrich_entity(e)
    document_map["glossary"] = build_glossary(entities)
    document_map["palette"] = build_palette()
    return document_map
