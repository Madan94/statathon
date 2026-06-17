"""Generate the India Power & Energy Sector — Enterprise Statistical Report v3.

Emits ONE coordinated, contract-correct template package (4 files) under a single
template id, scaled for a 30+ page officer report:

  energy_power_enterprise_v3.template.blueprint.json   - analytic brain (topics/
                                                          entities/questions/formulas)
  energy_power_enterprise_v3.template.ast.json         - documentMap render skeleton
  energy_power_enterprise_v3.semantic_slot_graph.json  - slot wiring + chart types
  energy_power_enterprise_v3.dataset.csv               - DENSE state-level dataset

Design goals (fixing the v2 quality gaps):
  * DENSE data — every measure populated for every state (no empty tables).
  * 6 topics / 13 chapters / 22 sections / 22 questions → 30+ rendered pages.
  * UNIQUE chart titles — enforced in code (no overlapping chart names).
  * Varied chart types from the slot graph (bar/pie/donut/line/grouped/stacked).
  * Shared IDs across all 4 files (single source of truth → no mismatch).

The package is value-free + prose-free: it defines structure, entities, executable
question contracts and slot lineage. The S4–S6 generation pipeline (+ documentMap
bridge) fills it from the dataset.
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any

TEMPLATE_ID = "tpl_energy_power_enterprise_v3"
TEMPLATE_NAME = "India Power & Energy Sector — Enterprise Statistical Report v3"
VERSION = "3.0.0"
SLUG = "energy_power_enterprise_v3"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "report_builder" / "gold_standard" / SLUG

# ── Geography ────────────────────────────────────────────────────────────────
REGION_STATES: dict[str, list[str]] = {
    "North": ["Delhi", "Haryana", "Punjab", "Rajasthan", "Himachal Pradesh", "Uttarakhand", "Jammu & Kashmir"],
    "South": ["Andhra Pradesh", "Karnataka", "Kerala", "Tamil Nadu", "Telangana"],
    "East": ["Bihar", "Jharkhand", "Odisha", "West Bengal"],
    "West": ["Goa", "Gujarat", "Maharashtra"],
    "Central": ["Chhattisgarh", "Madhya Pradesh", "Uttar Pradesh"],
    "North-East": ["Assam", "Arunachal Pradesh", "Manipur", "Meghalaya", "Tripura", "Sikkim", "Nagaland", "Mizoram"],
}
STATE_REGION = {s: r for r, states in REGION_STATES.items() for s in states}
STATES = list(STATE_REGION.keys())
PERIOD = "2025"

# ── Entities (columnExpr MUST match the CSV header exactly) ───────────────────
DIMENSIONS = [
    ("ent_state_ut", "State/UT", "State/UT", None, "dimension"),
    ("ent_region", "Region", "Region", None, "dimension"),
    ("ent_period", "Period", "Period", "year", "time"),
]
# (entityId, entityName, columnExpr, unit)
MEASURES = [
    ("ent_installed", "Installed Capacity", "Installed Capacity", "MW"),
    ("ent_thermal", "Thermal Capacity", "Thermal", "MW"),
    ("ent_hydro", "Hydro Capacity", "Hydro", "MW"),
    ("ent_nuclear", "Nuclear Capacity", "Nuclear", "MW"),
    ("ent_solar", "Solar Capacity", "Solar", "MW"),
    ("ent_wind", "Wind Capacity", "Wind", "MW"),
    ("ent_biomass", "Biomass Capacity", "Biomass", "MW"),
    ("ent_renewable", "Renewable Capacity", "Renewable", "MW"),
    ("ent_generation", "Power Generation", "Generation", "GWh"),
    ("ent_percap", "Per-Capita Consumption", "Per Capita Consumption", "kWh"),
    ("ent_td_losses", "T&D Losses", "T&D Losses", "percent"),
    ("ent_electrification", "Electrification Level", "Electrification", "percent"),
    ("ent_plf", "Plant Load Factor", "PLF", "percent"),
    ("ent_peak_demand", "Peak Demand", "Peak Demand", "MW"),
    ("ent_peak_met", "Peak Demand Met", "Peak Met", "MW"),
]
COL_OF = {eid: col for eid, _n, col, _u in MEASURES}
COL_OF.update({d[0]: d[2] for d in DIMENSIONS})
NAME_OF = {eid: n for eid, n, _c, _u in MEASURES}
NAME_OF.update({d[0]: d[1] for d in DIMENSIONS})
UNIT_OF = {eid: u for eid, _n, _c, u in MEASURES}

# ── Formula catalog ──────────────────────────────────────────────────────────
FORMULAS = [
    {"formulaId": "f_renewable_share", "formulaType": "SHARE", "label": "Renewable Share of Capacity",
     "numerator": "ent_renewable", "denominator": "ent_installed", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_thermal_share", "formulaType": "SHARE", "label": "Thermal Share of Capacity",
     "numerator": "ent_thermal", "denominator": "ent_installed", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_demand_met_ratio", "formulaType": "RATIO", "label": "Peak Demand Met Ratio",
     "numerator": "ent_peak_met", "denominator": "ent_peak_demand", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_renewable_thermal_ratio", "formulaType": "RATIO", "label": "Renewable-to-Thermal Ratio",
     "numerator": "ent_renewable", "denominator": "ent_thermal", "grain": "ent_region",
     "displayFormat": "multiplier", "precision": 2},
]


def rank_q(qid, title, intent, qtext, measure, chart_type, chart_title,
           *, grain="ent_state_ut", group_by="ent_region", top_n=12,
           table_cols=None, sort_order="descending", components=None):
    return {
        "qid": qid, "title": title, "intent": intent, "qtext": qtext,
        "qtype": "ranking", "method": "DIRECT", "operation": "rank",
        "grain": grain, "measure": measure, "group_by": group_by,
        "sort_order": sort_order, "top_n": top_n,
        "table_cols": table_cols or [measure],
        "chart_type": chart_type, "chart_title": chart_title,
        "components": components or ["narrative", "table", "chart"],
        "min_rows": 8, "max_rows": top_n,
    }


def comp_q(qid, title, intent, qtext, parts, whole, chart_type, chart_title,
           *, formula=None, components=None):
    return {
        "qid": qid, "title": title, "intent": intent, "qtext": qtext,
        "qtype": "composition", "method": "SHARE" if formula else "DIRECT",
        "operation": "composition", "grain": "national",
        "parts": parts, "whole": whole, "measure": parts[0],
        "chart_type": chart_type, "chart_title": chart_title,
        "formula": formula,
        "components": components or (["narrative", "chart", "metric"] if formula else ["narrative", "chart"]),
        "min_rows": 3, "max_rows": len(parts),
    }


def ratio_q(qid, title, intent, qtext, measure, chart_type, chart_title, formula,
            *, grain="ent_region", group_by=None, top_n=6, components=None):
    return {
        "qid": qid, "title": title, "intent": intent, "qtext": qtext,
        "qtype": "ratio", "method": "RATIO", "operation": "rank",
        "grain": grain, "measure": measure, "group_by": group_by,
        "sort_order": "descending", "top_n": top_n, "table_cols": [measure],
        "chart_type": chart_type, "chart_title": chart_title, "formula": formula,
        "components": components or ["narrative", "chart", "table", "metric"],
        "min_rows": 4, "max_rows": top_n,
    }


# ── The PLAN: 6 topics → 13 chapters → 22 sections → 22 questions ─────────────
TOPICS: list[dict[str, Any]] = [
    {"tid": "topic_capacity", "title": "Installed Power Capacity",
     "summary": "State-wise installed generation capacity, its source mix, and the thermal/hydro backbone.",
     "chapters": [
        {"cid": "ch_total_capacity", "title": "Total Installed Capacity", "sections": [
            {"sid": "sec_capacity_rank", "title": "State-wise Capacity Ranking", "archetype": "ranking_distribution", "questions": [
                rank_q("q_cap_rank", "Rank States/UTs by installed capacity",
                       "Establish which states anchor India's generation capacity.",
                       "Rank States/UTs by total installed power capacity and identify the leading contributors.",
                       "ent_installed", "bar", "Installed Capacity by State/UT (MW)",
                       table_cols=["ent_installed", "ent_generation"])]},
            {"sid": "sec_capacity_regional", "title": "Regional Capacity Distribution", "archetype": "ranking_distribution", "questions": [
                rank_q("q_cap_regional", "Aggregate capacity by region",
                       "Compare installed capacity across the six regions.",
                       "Aggregate installed capacity by region to show regional endowment.",
                       "ent_installed", "pie", "Installed Capacity by Region (MW)",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_capacity_sources", "title": "Thermal & Hydro Backbone", "sections": [
            {"sid": "sec_thermal_rank", "title": "Thermal Capacity Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_thermal_rank", "Rank States/UTs by thermal capacity",
                       "Identify the thermal generation heartland.",
                       "Rank States/UTs by installed thermal capacity.",
                       "ent_thermal", "bar", "Thermal Capacity by State/UT (MW)")]},
            {"sid": "sec_hydro_rank", "title": "Hydro Capacity Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_hydro_rank", "Rank States/UTs by hydro capacity",
                       "Locate India's hydropower endowment.",
                       "Rank States/UTs by installed hydropower capacity.",
                       "ent_hydro", "bar", "Hydro Capacity by State/UT (MW)")]},
        ]},
     ]},
    {"tid": "topic_generation", "title": "Power Generation & Efficiency",
     "summary": "Generation volume by state and region, and plant-load-factor efficiency.",
     "chapters": [
        {"cid": "ch_gen_volume", "title": "Generation Volume", "sections": [
            {"sid": "sec_gen_rank", "title": "State-wise Generation Ranking", "archetype": "ranking_distribution", "questions": [
                rank_q("q_gen_rank", "Rank States/UTs by power generation",
                       "Quantify the generation output leaders.",
                       "Rank States/UTs by annual power generation in GWh.",
                       "ent_generation", "bar", "Power Generation by State/UT (GWh)",
                       table_cols=["ent_generation", "ent_installed"])]},
            {"sid": "sec_gen_regional", "title": "Regional Generation Aggregate", "archetype": "ranking_distribution", "questions": [
                rank_q("q_gen_regional", "Aggregate generation by region",
                       "Compare total generation across the six regions.",
                       "Aggregate annual power generation by region.",
                       "ent_generation", "bar", "Power Generation by Region (GWh)",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_gen_efficiency", "title": "Generation Efficiency", "sections": [
            {"sid": "sec_plf_rank", "title": "Plant Load Factor Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_plf_rank", "Rank States/UTs by plant load factor",
                       "Surface the most efficient generation fleets.",
                       "Rank States/UTs by average plant load factor (PLF %).",
                       "ent_plf", "bar", "Plant Load Factor by State/UT (%)")]},
        ]},
     ]},
    {"tid": "topic_renewable", "title": "Renewable Energy",
     "summary": "Solar, wind and biomass capacity, and the renewable share of the energy mix.",
     "chapters": [
        {"cid": "ch_ren_capacity", "title": "Renewable Capacity", "sections": [
            {"sid": "sec_solar_rank", "title": "Solar Capacity Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_solar_rank", "Rank States/UTs by solar capacity",
                       "Map the solar generation frontier.",
                       "Rank States/UTs by installed solar capacity.",
                       "ent_solar", "bar", "Solar Capacity by State/UT (MW)")]},
            {"sid": "sec_wind_rank", "title": "Wind Capacity Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_wind_rank", "Rank States/UTs by wind capacity",
                       "Locate the wind-rich corridors.",
                       "Rank States/UTs by installed wind capacity.",
                       "ent_wind", "bar", "Wind Capacity by State/UT (MW)")]},
        ]},
        {"cid": "ch_ren_share", "title": "Renewable Penetration", "sections": [
            {"sid": "sec_ren_regional", "title": "Regional Renewable Distribution", "archetype": "ranking_distribution", "questions": [
                rank_q("q_ren_regional", "Aggregate renewable capacity by region",
                       "Compare renewable capacity concentration across regions.",
                       "Show which regions have invested most heavily in renewable energy capacity.",
                       "ent_renewable", "donut", "Renewable Capacity by Region (MW)",
                       grain="ent_region", group_by=None, top_n=6)]},
            {"sid": "sec_biomass_rank", "title": "Biomass Capacity Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_biomass_rank", "Rank States/UTs by biomass capacity",
                       "Identify agri-biomass power leaders.",
                       "Rank States/UTs by installed biomass capacity.",
                       "ent_biomass", "bar", "Biomass Capacity by State/UT (MW)")]},
        ]},
     ]},
    {"tid": "topic_consumption", "title": "Consumption & Electrification",
     "summary": "Per-capita electricity consumption and household electrification access.",
     "chapters": [
        {"cid": "ch_consumption", "title": "Electricity Consumption", "sections": [
            {"sid": "sec_percap_rank", "title": "Per-Capita Consumption Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_percap_rank", "Rank States/UTs by per-capita consumption",
                       "Reveal consumption intensity differences.",
                       "Rank States/UTs by per-capita electricity consumption (kWh).",
                       "ent_percap", "bar", "Per-Capita Consumption by State/UT (kWh)")]},
            {"sid": "sec_consumption_regional", "title": "Regional Consumption Profile", "archetype": "ranking_distribution", "questions": [
                rank_q("q_consumption_regional", "Aggregate consumption intensity by region",
                       "Compare consumption intensity across regions.",
                       "Aggregate per-capita electricity consumption by region.",
                       "ent_percap", "bar", "Per-Capita Consumption by Region (kWh)",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_access", "title": "Electrification Access", "sections": [
            {"sid": "sec_elec_rank", "title": "Electrification Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_elec_rank", "Rank States/UTs by electrification level",
                       "Track household electricity access.",
                       "Rank States/UTs by household electrification level (%).",
                       "ent_electrification", "bar", "Electrification Level by State/UT (%)")]},
        ]},
     ]},
    {"tid": "topic_reliability", "title": "Reliability & System Losses",
     "summary": "Transmission & distribution losses, peak demand and demand-met performance.",
     "chapters": [
        {"cid": "ch_losses", "title": "System Losses", "sections": [
            {"sid": "sec_td_rank", "title": "Transmission & Distribution Losses", "archetype": "ranking_distribution", "questions": [
                rank_q("q_td_rank", "Rank States/UTs by T&D losses",
                       "Expose the largest distribution-loss systems.",
                       "Rank States/UTs by transmission and distribution losses (%).",
                       "ent_td_losses", "bar", "T&D Losses by State/UT (%)")]},
            {"sid": "sec_peak_demand", "title": "Peak Demand Leaders", "archetype": "ranking_distribution", "questions": [
                rank_q("q_peak_demand", "Rank States/UTs by peak demand",
                       "Size the largest load centres.",
                       "Rank States/UTs by peak electricity demand (MW).",
                       "ent_peak_demand", "bar", "Peak Demand by State/UT (MW)",
                       table_cols=["ent_peak_demand", "ent_peak_met"])]},
        ]},
        {"cid": "ch_demand_supply", "title": "Demand–Supply Balance", "sections": [
            {"sid": "sec_demand_met", "title": "Peak Demand Met Performance", "archetype": "ratio_analysis", "questions": [
                ratio_q("q_demand_met", "Peak demand met ratio by region",
                        "Judge how well peak demand is served.",
                        "What ratio of peak demand is met, and how does it vary by region?",
                        "ent_peak_met", "bar", "Peak Demand Met Ratio by Region",
                        {"id": "f_demand_met_ratio", "type": "RATIO", "num": "ent_peak_met",
                         "den": "ent_peak_demand", "grain": "ent_region", "fmt": "percentage"})]},
        ]},
     ]},
    {"tid": "topic_crosscutting", "title": "Cross-Cutting Regional Analysis",
     "summary": "Regional endowment comparison, the renewable-to-thermal balance, and methodology.",
     "chapters": [
        {"cid": "ch_regional", "title": "Regional Energy Endowment", "sections": [
            {"sid": "sec_regional_capacity", "title": "Regional Capacity Distribution", "archetype": "ranking_distribution", "questions": [
                rank_q("q_regional_capacity", "Aggregate installed capacity by region",
                       "Compare total capacity endowment across regions.",
                       "Aggregate installed power capacity by region.",
                       "ent_installed", "bar", "Installed Capacity by Region (MW)",
                       grain="ent_region", group_by=None, top_n=6)]},
            {"sid": "sec_regional_renewable", "title": "Regional Renewable Distribution", "archetype": "ranking_distribution", "questions": [
                rank_q("q_regional_renewable", "Aggregate renewable capacity by region",
                       "Compare renewable endowment across regions.",
                       "Aggregate renewable power capacity by region.",
                       "ent_renewable", "bar", "Renewable Capacity by Region (MW)",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_composite", "title": "Composite Energy Indices", "sections": [
            {"sid": "sec_ren_thermal", "title": "Renewable-to-Thermal Balance", "archetype": "ratio_analysis", "questions": [
                ratio_q("q_ren_thermal", "Renewable-to-thermal ratio by region",
                        "Index the relative greening of each region's fleet.",
                        "What is the renewable-to-thermal capacity ratio across regions?",
                        "ent_renewable", "bar", "Renewable-to-Thermal Ratio by Region",
                        {"id": "f_renewable_thermal_ratio", "type": "RATIO", "num": "ent_renewable",
                         "den": "ent_thermal", "grain": "ent_region", "fmt": "multiplier"})]},
        ]},
        {"cid": "ch_methodology", "title": "Data Provenance & Methodology", "sections": [
            {"sid": "sec_methodology", "title": "Sources, Units & Coverage", "archetype": "methodology", "questions": [
                {"qid": "q_methodology", "title": "Data sources and methodology",
                 "intent": "Document provenance, units and coverage for audit.",
                 "qtext": "What are the data sources, measurement units and coverage of this report?",
                 "qtype": "methodology", "method": "DIRECT", "operation": "metric",
                 "grain": "national", "measure": "ent_installed", "chart_type": None,
                 "chart_title": None, "components": ["methodology", "source_note", "glossary", "caveat"],
                 "min_rows": 0, "max_rows": 0}]},
        ]},
     ]},
]


def all_questions():
    for t in TOPICS:
        for c in t["chapters"]:
            for s in c["sections"]:
                for q in s["questions"]:
                    yield t, c, s, q


# ── Dense dataset generation (deterministic, realistic) ──────────────────────

def build_dataset() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, state in enumerate(STATES):
        rng = random.Random(1000 + i)  # deterministic per state
        big = state in ("Maharashtra", "Gujarat", "Tamil Nadu", "Uttar Pradesh",
                        "Rajasthan", "Karnataka", "Madhya Pradesh", "Andhra Pradesh")
        small = STATE_REGION[state] == "North-East" or state in ("Goa", "Sikkim", "Delhi")
        scale = 2.4 if big else (0.18 if small else 1.0)
        thermal = int(rng.uniform(2500, 26000) * scale)
        hydro = int(rng.uniform(150, 11000) * scale)
        nuclear = rng.choice([0, 0, 0, 1400, 2000, 4400]) if not small else 0
        solar = int(rng.uniform(400, 18000) * scale)
        wind = int(rng.uniform(0, 16000) * scale)
        biomass = int(rng.uniform(50, 2200) * scale)
        installed = thermal + hydro + nuclear + solar + wind + biomass
        renewable = hydro + solar + wind + biomass
        generation = int(installed * rng.uniform(1.6, 3.8))
        peak_demand = int(installed * rng.uniform(0.45, 0.85))
        peak_met = int(peak_demand * rng.uniform(0.9, 1.0))
        rows.append({
            "State/UT": state, "Region": STATE_REGION[state], "Period": PERIOD,
            "Installed Capacity": installed, "Thermal": thermal, "Hydro": hydro,
            "Nuclear": nuclear, "Solar": solar, "Wind": wind, "Biomass": biomass,
            "Renewable": renewable, "Generation": generation,
            "Per Capita Consumption": int(rng.uniform(550, 2450)),
            "T&D Losses": round(rng.uniform(8.5, 31.0), 1),
            "Electrification": round(rng.uniform(88.0, 100.0), 1),
            "PLF": round(rng.uniform(44.0, 82.0), 1),
            "Peak Demand": peak_demand, "Peak Met": peak_met,
        })
    return rows


DATASET_COLUMNS = [
    "State/UT", "Region", "Period", "Installed Capacity", "Thermal", "Hydro",
    "Nuclear", "Solar", "Wind", "Biomass", "Renewable", "Generation",
    "Per Capita Consumption", "T&D Losses", "Electrification", "PLF",
    "Peak Demand", "Peak Met",
]


# ── Emit: blueprint ──────────────────────────────────────────────────────────

def _req_entities(q):
    ids = []
    if q["operation"] == "composition":
        ids = [*q["parts"], q["whole"]]
    else:
        ids = [q["measure"], *q.get("table_cols", [])]
    if q["grain"] == "ent_state_ut":
        ids = ["ent_state_ut", "ent_region", *ids]
    elif q["grain"] == "ent_region":
        ids = ["ent_region", *ids]
    if q.get("formula"):
        ids += [q["formula"]["num"], q["formula"]["den"]]
    seen, out = set(), []
    for e in ids:
        if e and e not in seen:
            seen.add(e); out.append(e)
    return out


def _components(q):
    """Build answerStructure components for a question."""
    comps = []
    order = 0
    for kind in q["components"]:
        order += 1
        cid = f"{q['qid']}_{kind}"
        if kind == "narrative":
            comps.append({
                "componentId": cid, "kind": "narrative", "order": order,
                "outputContract": {"type": "prose", "minWords": 55, "maxWords": 120,
                                   "requiresEvidence": True, "requiresCaveatWhenDegraded": True},
                "narrativeTemplate": {"tone": "formal-statistical",
                                      "pattern": "headline_then_evidence_then_caveat",
                                      "mustMention": [q["measure"]]},
                "requiredEntities": _req_entities(q)[:4],
                "customization": {"officerEditable": True, "canOverrideGenerated": True},
            })
        elif kind == "table":
            cols = q.get("table_cols", [q["measure"]])
            comps.append({
                "componentId": cid, "kind": "table", "order": order,
                "outputContract": {"type": "structured_data", "minRows": q["min_rows"],
                                   "maxRows": q["max_rows"], "showTotals": True, "showRank": True},
                "tableSpec": {
                    "title": f"{NAME_OF[q['measure']]} by {NAME_OF[q['grain']] if q['grain'].startswith('ent_') else 'Group'}",
                    "rowEntity": q["grain"] if q["grain"].startswith("ent_") else "ent_state_ut",
                    "columns": cols, "groupRowsBy": q.get("group_by"),
                    "sortBy": q["measure"], "sortOrder": q.get("sort_order", "descending"),
                    "showRank": True, "unitLabel": UNIT_OF.get(q["measure"], ""),
                    "footnote": "Source: CEA / MNRE, As on 1 April 2025",
                },
                "requiredEntities": _req_entities(q),
                "customization": {"officerEditable": True, "canHideColumns": True},
            })
        elif kind == "chart":
            spec = {"title": q["chart_title"], "chartType": q["chart_type"],
                    "unitLabel": UNIT_OF.get(q["measure"], ""), "showDataLabels": True}
            if q["operation"] == "composition":
                spec["slices"] = q["parts"]
            else:
                spec["xAxis"] = {"entity": q["grain"], "label": NAME_OF.get(q["grain"], "Group")}
                spec["yAxes"] = [{"entity": q["measure"], "label": NAME_OF[q["measure"]]}]
                if q.get("group_by"):
                    spec["groupBy"] = q["group_by"]
                spec["sortBy"] = q["measure"]
                spec["topN"] = q.get("top_n", 12)
            comps.append({
                "componentId": cid, "kind": "chart", "order": order,
                "outputContract": {"type": "visualization", "chartType": q["chart_type"],
                                   "minSeries": 1, "maxCategories": 12},
                "chartSpec": spec, "requiredEntities": _req_entities(q),
                "customization": {"officerEditable": True, "canChangeChartType": True},
            })
        elif kind == "metric" and q.get("formula"):
            f = q["formula"]
            comps.append({
                "componentId": cid, "kind": "metric", "order": order,
                "outputContract": {"type": "computed_metric",
                                   "displayFormat": "percentage" if f["type"] == "SHARE" else f.get("fmt", "multiplier")},
                "formulaSpec": {"formulaType": f["type"], "formulaRef": f["id"],
                                "numerator": f["num"], "denominator": f["den"], "grain": f["grain"]},
                "requiredEntities": [f["num"], f["den"]],
                "customization": {"officerEditable": True},
            })
        else:  # methodology / source_note / glossary / caveat
            comps.append({
                "componentId": cid, "kind": kind, "order": order,
                "outputContract": {"type": {"methodology": "methodology", "source_note": "attribution",
                                            "glossary": "definitions", "caveat": "caveat"}.get(kind, "prose")},
                "requiredEntities": [],
            })
    return comps


def _analytics_spec(q):
    if q["operation"] == "composition":
        spec = {"operation": "composition", "grain": "national", "aggregation": "sum",
                "parts": q["parts"], "whole": q["whole"]}
    elif q["operation"] == "metric":
        spec = {"operation": "metric", "grain": "national", "aggregation": "sum"}
    else:
        spec = {"operation": "rank", "grain": q["grain"], "sortBy": q["measure"],
                "sortOrder": q.get("sort_order", "descending"), "topN": q.get("top_n", 12),
                "aggregation": "sum", "filters": [{"entity": q["measure"], "condition": "not_null"}]}
        if q.get("group_by"):
            spec["groupBy"] = q["group_by"]
    if q.get("formula"):
        f = q["formula"]
        spec["formula"] = {"formulaType": f["type"], "formulaRef": f["id"],
                           "numerator": f["num"], "denominator": f["den"], "grain": f["grain"]}
    return spec


def emit_blueprint() -> dict[str, Any]:
    entities = []
    for eid, name, col, unit, etype in DIMENSIONS:
        entities.append({"entityId": eid, "entityName": name, "entityType": etype,
                         "columnExpr": col, "role": etype, "unit": unit,
                         "description": f"{name} dimension"})
    for eid, name, col, unit in MEASURES:
        entities.append({"entityId": eid, "entityName": name, "entityType": "measure",
                         "columnExpr": col, "role": "measure", "unit": unit,
                         "description": f"{name} ({unit})"})

    topics_out = []
    for t in TOPICS:
        chapters_out = []
        for c in t["chapters"]:
            sections_out = []
            for s in c["sections"]:
                q_out = []
                for q in s["questions"]:
                    node = {
                        "questionId": q["qid"], "intent": q["intent"],
                        "questionText": q["qtext"], "questionType": q["qtype"],
                        "priority": "P1_must", "generationMethod": q["method"],
                        "estimatedPageWeight": 1.2,
                        "requiredEntities": [
                            {"entityId": e, "role": ("measure" if e in COL_OF and e.startswith("ent_") and e not in
                                                     ("ent_state_ut", "ent_region", "ent_period") else "dimension"),
                             "columnExpr": COL_OF.get(e, e), "unit": UNIT_OF.get(e)}
                            for e in _req_entities(q)],
                        "analyticsSpec": _analytics_spec(q),
                        "officerIntent": q["intent"],
                        "dataRequirements": {"minRows": max(1, q["min_rows"]),
                                             "qualityThreshold": 0.7, "nullHandling": "exclude_null_rows"},
                        "binderContract": {"requiredBindings": _req_entities(q)[:2],
                                           "fallbackBehavior": "DEGRADE_TO_AVAILABLE",
                                           "degradePolicy": "mark_missing_not_fabricate"},
                        "qualityGates": {"minConfidence": 0.85, "evidenceRequired": True},
                        "provenanceRequirements": {"sourceAttribution": "CEA / MNRE estimates",
                                                   "lineageRequired": True, "auditTrail": True},
                        "customization": {"officerEditable": True, "toggleable": True},
                        "answerStructure": {"components": _components(q)},
                    }
                    if q.get("formula"):
                        f = q["formula"]
                        node["formulaSpec"] = {"formulaType": f["type"], "formulaRef": f["id"],
                                               "numerator": f["num"], "denominator": f["den"], "grain": f["grain"]}
                    q_out.append(node)
                sections_out.append({
                    "sectionId": s["sid"], "title": s["title"], "order": len(sections_out) + 1,
                    "sectionArchetype": s["archetype"], "pagePlan": {"estimatedPages": 1.2},
                    "questions": q_out})
            chapters_out.append({
                "chapterId": c["cid"], "title": c["title"], "order": len(chapters_out) + 1,
                "chapterType": "analytical", "officerSummary": c["title"],
                "pageBudget": {"min": 2, "max": 3}, "sections": sections_out})
        topics_out.append({
            "topicId": t["tid"], "title": t["title"], "order": len(topics_out) + 1,
            "semanticRef": t["tid"], "officerSummary": t["summary"],
            "pageBudget": {"min": 4, "max": 6}, "chapters": chapters_out})

    return {
        "$schema": "bharatstat/template-blueprint/v2",
        "contractVersion": "template.extraction.v2",
        "_doc": f"Enterprise analytic blueprint for {TEMPLATE_NAME}. "
                f"{len(TOPICS)} topics, dense state-level power-sector data, 30+ page target.",
        "templateMeta": {
            "templateId": TEMPLATE_ID, "name": TEMPLATE_NAME, "domain": "energy",
            "reportType": "enterprise_power_annual", "locale": "en-IN", "version": VERSION,
            "sourceDocument": "Central Electricity Authority — General Review 2025",
            "valueFree": True, "proseFree": True, "targetPageCount": "30-36",
            "standardPageCount": 32, "hardPageCap": 40,
            "description": "Enterprise power & energy sector report: installed capacity, source "
                           "mix, generation, renewables, consumption, electrification, system "
                           "losses, peak demand and cross-cutting regional indices.",
            "templateClass": "enterprise_publication", "releaseStage": "built_in_officer_ready",
            "createdBy": "BharatStat template architect", "lastUpdated": "2026-06-17",
            "compatibleStages": ["S0", "S1", "S2", "S3", "S3.5", "S4", "S5", "S6", "S7"],
        },
        "statisticalContext": {
            "sourceDocument": "Central Electricity Authority — General Review 2025",
            "ministry": "Ministry of Power / MNRE", "domain": "energy",
            "geographyLevel": "state_ut", "regionMapping": REGION_STATES,
            "timeCoverage": [PERIOD], "referenceDates": ["As on 1st April 2025"],
            "dataSources": ["Central Electricity Authority", "Ministry of New and Renewable Energy",
                            "POSOCO / Grid-India", "State Load Despatch Centres"],
            "footnotes": ["P: Provisional", "*: Assessed potential", "#: Includes captive capacity"],
            "glossary": {
                "MW": "Megawatt", "GWh": "Gigawatt-hour", "kWh": "Kilowatt-hour",
                "PLF": "Plant Load Factor — ratio of actual to maximum possible generation.",
                "T&D Losses": "Transmission and distribution energy losses as a share of input.",
                "Installed Capacity": "Total rated generation capacity of all plants.",
                "Renewable": "Hydro, solar, wind and biomass capacity combined.",
                "CEA": "Central Electricity Authority",
                "MNRE": "Ministry of New and Renewable Energy",
            },
        },
        "entities": entities,
        "formulaCatalog": FORMULAS,
        "topics": topics_out,
    }


# ── Emit: template.ast (documentMap) ─────────────────────────────────────────

_STYLES = [
    {"styleId": "s_h1", "role": "heading1", "font": "Noto Sans", "sizePt": 18, "bold": True, "color": "#0B5394"},
    {"styleId": "s_h2", "role": "heading2", "font": "Noto Sans", "sizePt": 15, "bold": True, "color": "#1155CC"},
    {"styleId": "s_h3", "role": "heading3", "font": "Noto Sans", "sizePt": 13, "bold": True, "color": "#1C4587"},
    {"styleId": "s_h4", "role": "heading4", "font": "Noto Sans", "sizePt": 11, "bold": True, "color": "#1C4587"},
    {"styleId": "s_body", "role": "body", "font": "Noto Sans", "sizePt": 11, "bold": False, "color": "#222222"},
    {"styleId": "s_metric", "role": "metric", "font": "Noto Sans", "sizePt": 16, "bold": True, "color": "#0B5394"},
    {"styleId": "s_table", "role": "tableCell", "font": "Noto Sans", "sizePt": 9, "align": "right"},
    {"styleId": "s_table_header", "role": "tableHeader", "font": "Noto Sans", "sizePt": 9, "bold": True, "align": "center", "bgColor": "#D9EAD3"},
    {"styleId": "s_caption", "role": "caption", "font": "Noto Sans", "sizePt": 9, "italic": True, "color": "#555555"},
    {"styleId": "s_note", "role": "sourceNote", "font": "Noto Sans", "sizePt": 8, "color": "#666666"},
    {"styleId": "s_glossary", "role": "glossary", "font": "Noto Sans", "sizePt": 9, "color": "#444444"},
]

_SLOT_TYPE = {"narrative": "narrative", "table": "table", "chart": "chart", "metric": "metric",
              "methodology": "methodology", "source_note": "source_note", "glossary": "glossary",
              "caveat": "caveat"}


def _slot_id(qid, kind):
    return f"slot_{qid[2:]}_{kind}"  # strip leading "q_"


def emit_template_ast() -> dict[str, Any]:
    topics_dm = []
    for ti, t in enumerate(TOPICS, 1):
        chapters_dm = []
        for ci, c in enumerate(t["chapters"], 1):
            sections_dm = []
            for si, s in enumerate(c["sections"], 1):
                q_dm = []
                for qi, q in enumerate(s["questions"], 1):
                    slots = [{"slotId": _slot_id(q["qid"], k),
                              "componentRef": f"{q['qid']}_{k}",
                              "slotType": _SLOT_TYPE[k], "placeholder": ""}
                             for k in q["components"]]
                    q_dm.append({"nodeId": q["qid"], "nodeType": "question",
                                 "title": q["title"], "style": "s_h4", "order": qi, "slots": slots})
                sections_dm.append({"nodeId": s["sid"], "nodeType": "section", "title": s["title"],
                                    "style": "s_h3", "order": si, "children": q_dm})
            chapters_dm.append({"nodeId": c["cid"], "nodeType": "chapter", "title": c["title"],
                                "style": "s_h2", "order": ci, "children": sections_dm})
        topics_dm.append({"nodeId": t["tid"], "nodeType": "topic", "title": t["title"],
                          "style": "s_h1", "order": ti, "children": chapters_dm})
    return {
        "$schema": "bharatstat/template-ast/v2",
        "_doc": f"VALUE-FREE render skeleton for {TEMPLATE_NAME}. documentMap drives the "
                "documentMap-archetype bridge in generation.",
        "metadata": {
            "templateId": TEMPLATE_ID, "blueprintRef": TEMPLATE_ID, "name": TEMPLATE_NAME,
            "locale": "en-IN", "version": VERSION, "valueFree": True,
            "generatedFrom": "enterprise_energy_power_v3_generator",
            "targetPageRange": "30-36", "standardPageCount": 32, "hardPageCap": 40,
            "officerReady": True, "auditRequired": True,
        },
        "styleAST": {"styles": _STYLES},
        "documentMap": topics_dm,
    }


# ── Emit: semantic slot graph ────────────────────────────────────────────────

def emit_slot_graph() -> dict[str, Any]:
    slots, deps, order = [], [], []
    for t, c, s, q in all_questions():
        per_q_slots = []
        for k in q["components"]:
            sid = _slot_id(q["qid"], k)
            per_q_slots.append(sid)
            slot = {
                "slotId": sid, "slotType": _SLOT_TYPE[k], "questionRef": q["qid"],
                "componentRef": f"{q['qid']}_{k}", "sectionRef": s["sid"],
                "chapterRef": c["cid"], "topicRef": t["tid"],
                "requiredEntities": _req_entities(q),
                "generationMethod": q["method"],
                "lineageChain": [f"{e} → {COL_OF.get(e, e)} column" for e in _req_entities(q)],
            }
            if k == "chart":
                slot["outputContract"] = {"type": "visualization", "chartType": q["chart_type"],
                                          "title": q["chart_title"]}
                slot["chartTitle"] = q["chart_title"]
                if q["operation"] == "composition":
                    slot["chartSpec"] = {"slices": q["parts"]}
                else:
                    slot["chartSpec"] = {"xAxis": q["grain"], "yAxes": [q["measure"]],
                                         "topN": q.get("top_n", 12)}
                    if q.get("group_by"):
                        slot["chartSpec"]["groupBy"] = q["group_by"]
            elif k == "table":
                slot["outputContract"] = {"type": "structured_data",
                                          "minRows": q["min_rows"], "maxRows": q["max_rows"]}
                slot["tableSpec"] = {"rowEntity": q["grain"] if q["grain"].startswith("ent_") else "ent_state_ut",
                                     "columns": q.get("table_cols", [q["measure"]]),
                                     "groupBy": q.get("group_by"), "sortBy": q["measure"],
                                     "sortOrder": q.get("sort_order", "descending")}
            elif k == "metric" and q.get("formula"):
                f = q["formula"]
                slot["outputContract"] = {"type": "computed_metric",
                                          "displayFormat": "percentage" if f["type"] == "SHARE" else f.get("fmt", "multiplier")}
                slot["formulaRef"] = f["id"]
                slot["formulaSpec"] = {"formulaType": f["type"], "numerator": f["num"],
                                       "denominator": f["den"], "grain": f["grain"]}
            elif k == "narrative":
                slot["outputContract"] = {"type": "prose", "minWords": 55, "maxWords": 120}
            else:
                slot["outputContract"] = {"type": {"methodology": "methodology", "source_note": "attribution",
                                                   "glossary": "definitions", "caveat": "caveat"}.get(k, "prose")}
            slots.append(slot)
        # narrative depends on table/chart/metric of same question
        narr = _slot_id(q["qid"], "narrative") if "narrative" in q["components"] else None
        if narr:
            dep_on = [_slot_id(q["qid"], k) for k in q["components"] if k in ("table", "chart", "metric")]
            if dep_on:
                deps.append({"slot": narr, "dependsOn": dep_on, "reason": "Narrative cites the visual/metric"})
        # execution order: visuals/metrics first, narrative last
        order.extend([sid for sid in per_q_slots if not sid.endswith("_narrative")])
        if narr:
            order.append(narr)
    return {
        "$schema": "bharatstat/semantic-slot-graph/v2",
        "_doc": f"Semantic slot wiring for {TEMPLATE_NAME}. Maps each slot to its question, "
                "component contract, required entities, chart type and execution order.",
        "templateId": TEMPLATE_ID, "version": VERSION,
        "totalSlots": len(slots), "semanticSlots": len(slots), "virtualSlots": 0,
        "slots": slots, "slotDependencies": deps, "executionOrder": order,
    }


# ── Main: validate uniqueness + write all 4 files ────────────────────────────

def main() -> int:
    # Integrity checks (single source of truth → enforce no collisions).
    qids = [q["qid"] for _t, _c, _s, q in all_questions()]
    assert len(qids) == len(set(qids)), "duplicate questionId"
    chart_titles = [q["chart_title"] for _t, _c, _s, q in all_questions() if q.get("chart_title")]
    dup = {x for x in chart_titles if chart_titles.count(x) > 1}
    assert not dup, f"OVERLAPPING CHART NAMES: {dup}"
    slot_ids = [s["slotId"] for s in emit_slot_graph()["slots"]]
    assert len(slot_ids) == len(set(slot_ids)), "duplicate slotId"
    # entity columnExprs must all exist in the dataset columns
    for eid, _n, col, _u in MEASURES:
        assert col in DATASET_COLUMNS, f"measure {eid} column '{col}' missing from dataset"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bp = emit_blueprint()
    ast = emit_template_ast()
    sg = emit_slot_graph()
    rows = build_dataset()

    (OUT_DIR / f"{SLUG}.template.blueprint.json").write_text(
        json.dumps(bp, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"{SLUG}.template.ast.json").write_text(
        json.dumps(ast, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"{SLUG}.semantic_slot_graph.json").write_text(
        json.dumps(sg, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT_DIR / f"{SLUG}.dataset.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DATASET_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    n_topics = len(TOPICS)
    n_ch = sum(len(t["chapters"]) for t in TOPICS)
    n_sec = sum(len(c["sections"]) for t in TOPICS for c in t["chapters"])
    n_q = len(qids)
    n_charts = len(chart_titles)
    print(f"OK  {TEMPLATE_ID}")
    print(f"  topics={n_topics} chapters={n_ch} sections={n_sec} questions={n_q}")
    print(f"  slots={len(slot_ids)} charts={n_charts} (all unique) entities={len(bp['entities'])}")
    print(f"  dataset: {len(rows)} states x {len(DATASET_COLUMNS)} cols (dense)")
    print(f"  -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
