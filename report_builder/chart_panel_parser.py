"""Generic MoSPI chart title parser.

Extracts value-free semantic hints from chart/figure titles. The parser is not
PLFS-hardcoded: it uses the entity catalog's names, aliases, and valueDomain
members first, then applies small generic MoSPI conventions such as figure panel
labels and common sector/gender/status words.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_FIG_RE = re.compile(r"\bfig(?:ure)?\.?\s*(?P<number>\d+)\s*(?:\((?P<panel>[a-z])\))?", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GENERIC_ALIASES = {"average", "distribution", "distribution (%)", "worker", "rate", "share", "value"}


@dataclass
class ChartPanelSemantics:
    figureNumber: str = ""
    panel: str = ""
    measureRefs: list[str] = field(default_factory=list)
    dimensionRefs: list[str] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.3

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "measureRefs": list(self.measureRefs),
            "dimensionRefs": list(self.dimensionRefs),
            "filters": list(self.filters),
            "confidence": self.confidence,
        }
        if self.figureNumber:
            out["figureNumber"] = self.figureNumber
        if self.panel:
            out["panel"] = self.panel
        return out


def parse_chart_panel_title(title: str, entities: list[Any] | None = None) -> ChartPanelSemantics:
    text = str(title or "")
    text_lower = text.lower()
    tokens = set(_TOKEN_RE.findall(text_lower))
    parsed = ChartPanelSemantics()

    fig_match = _FIG_RE.search(text)
    if fig_match:
        parsed.figureNumber = fig_match.group("number") or ""
        parsed.panel = fig_match.group("panel") or ""

    catalog = _catalog_entities(entities or [])

    for entity in catalog:
        if entity["entityType"] == "measure" and _entity_matches(entity, text_lower, tokens):
            parsed.measureRefs.append(entity["entityId"])
        elif entity["entityType"] in ("dimension", "filter", "time"):
            matched_members = _matched_members(entity, text_lower, tokens)
            if matched_members:
                if entity["entityId"] not in parsed.dimensionRefs:
                    parsed.dimensionRefs.append(entity["entityId"])
                for member in matched_members:
                    parsed.filters.append({
                        "entityId": entity["entityId"],
                        "value": member,
                        "source": "chart_title",
                    })
            elif _entity_matches(entity, text_lower, tokens):
                parsed.dimensionRefs.append(entity["entityId"])

    _generic_member_fallbacks(parsed, catalog, text_lower, tokens)
    _prefer_explicit_measure(parsed, catalog, text_lower)

    parsed.measureRefs = _dedupe(parsed.measureRefs)
    parsed.dimensionRefs = _dedupe(parsed.dimensionRefs)
    parsed.filters = _dedupe_filters(parsed.filters)

    signal_count = len(parsed.measureRefs) + len(parsed.dimensionRefs) + len(parsed.filters)
    if parsed.figureNumber:
        signal_count += 1
    parsed.confidence = min(0.95, 0.35 + signal_count * 0.12)
    return parsed


def group_chart_panels(charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group physical chart panels into binder-level analytical groups."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    skipped_unbound: list[str] = []
    for chart in charts:
        measure = chart.get("measureEntityId") or ""
        if not measure:
            skipped_unbound.append(str(chart.get("chartId") or chart.get("id") or "<unknown>"))
            continue
        family = chart.get("chartFamily") or measure or chart.get("chartSubject") or chart.get("chartId") or "unknown"
        fig = str(chart.get("figureNumber") or "")
        key = (measure, fig or str(family).lower())
        group = groups.setdefault(key, {
            "groupId": f"chart_group_{_slug(measure or family)}_{fig or len(groups) + 1}",
            "measureEntityId": measure,
            "figureNumber": fig,
            "panels": [],
        })
        group["panels"].append({
            "chartId": chart.get("chartId"),
            "panel": chart.get("panel") or "",
            "filters": chart.get("filters") or [],
            "dimensionEntityId": chart.get("dimensionEntityId") or "",
        })
    if skipped_unbound:
        logger.warning(
            "Skipped %d chart panel(s) without measureEntityId while building binder groups: %s",
            len(skipped_unbound),
            ", ".join(skipped_unbound[:5]),
        )
    return list(groups.values())


def _catalog_entities(entities: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entity in entities:
        get = entity.get if isinstance(entity, dict) else lambda k, default=None: getattr(entity, k, default)
        entity_id = get("entityId") or ""
        if not entity_id:
            continue
        value_domain = get("valueDomain") or {}
        members = value_domain.get("members") if isinstance(value_domain, dict) else []
        out.append({
            "entityId": entity_id,
            "entityName": get("canonicalName") or get("name") or entity_id,
            "entityType": get("entityType") or "",
            "aliases": list(get("aliases") or []),
            "members": members if isinstance(members, list) else [],
        })
    return out


def _entity_matches(entity: dict[str, Any], text_lower: str, tokens: set[str]) -> bool:
    names = [entity["entityName"], *entity["aliases"]]
    for name in names:
        if str(name).lower().strip() in _GENERIC_ALIASES:
            continue
        if _phrase_matches(str(name), text_lower, tokens):
            return True
    return False


def _prefer_explicit_measure(parsed: ChartPanelSemantics, catalog: list[dict[str, Any]], text_lower: str) -> None:
    preferences: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("formal education", "education years", "years in formal"), ("education",)),
        (("earning", "earnings", "wage", "salary"), ("earnings", "monthly earnings")),
        (("weekly hours", "hours per week"), ("weekly hours",)),
        (("percentage distribution", "proportion of workers", "status in employment"), ("worker share",)),
    ]
    for triggers, entity_terms in preferences:
        if not any(trigger in text_lower for trigger in triggers):
            continue
        for entity in catalog:
            if entity["entityType"] != "measure":
                continue
            haystack = " ".join([entity["entityName"], *entity["aliases"]]).lower()
            if any(term in haystack for term in entity_terms):
                parsed.measureRefs = [entity["entityId"]]
                return


def _matched_members(entity: dict[str, Any], text_lower: str, tokens: set[str]) -> list[str]:
    matches: list[str] = []
    for member in entity.get("members") or []:
        if _phrase_matches(str(member), text_lower, tokens):
            matches.append(str(member))
    return matches


def _phrase_matches(phrase: str, text_lower: str, tokens: set[str]) -> bool:
    phrase_lower = phrase.lower().strip()
    if not phrase_lower:
        return False
    phrase_tokens = _TOKEN_RE.findall(phrase_lower)
    if len(phrase_tokens) == 1 and len(phrase_tokens[0]) <= 3:
        return phrase_tokens[0] in tokens
    return phrase_lower in text_lower or bool(phrase_tokens and set(phrase_tokens).issubset(tokens))


def _generic_member_fallbacks(parsed: ChartPanelSemantics, catalog: list[dict[str, Any]], text_lower: str, tokens: set[str]) -> None:
    def add_filter(entity_predicate, value: str) -> None:
        for entity in catalog:
            if entity_predicate(entity):
                if entity["entityId"] not in parsed.dimensionRefs:
                    parsed.dimensionRefs.append(entity["entityId"])
                parsed.filters.append({"entityId": entity["entityId"], "value": value, "source": "chart_title"})
                return

    if "rural" in tokens:
        add_filter(lambda e: "sector" in e["entityName"].lower() or "area" in [a.lower() for a in e["aliases"]], "Rural")
    if "urban" in tokens:
        add_filter(lambda e: "sector" in e["entityName"].lower() or "area" in [a.lower() for a in e["aliases"]], "Urban")
    if "male" in tokens:
        add_filter(lambda e: "gender" in e["entityName"].lower(), "Male")
    if "female" in tokens:
        add_filter(lambda e: "gender" in e["entityName"].lower(), "Female")
    if "persons" in tokens:
        add_filter(lambda e: "gender" in e["entityName"].lower(), "Persons")
    if "usual" in tokens and "status" in tokens:
        add_filter(lambda e: "activity status" in e["entityName"].lower(), "Usual Status (ps+ss)")
    if "cws" in tokens or "weekly" in tokens:
        add_filter(lambda e: "activity status" in e["entityName"].lower(), "Current Weekly Status")
    if "15" in tokens and "above" in tokens:
        add_filter(lambda e: "age" in e["entityName"].lower(), "15 years and above")


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def _dedupe_filters(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in filters:
        key = (str(item.get("entityId") or ""), str(item.get("value") or ""))
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "chart"
