"""Generate the Sixth Economic Census — Establishment & Employment Statistics (v1).

Acts as the full extraction + binder template module for the REAL 6th Economic
Census establishment microdata (``processed_dataset/analysis_30_processed.xlsx``,
6,512 establishments x 27 columns). It:

  1. Reads + cleans the real microdata and aggregates it to a DENSE state-level
     dataset (one row per State/UT, every measure populated) — honouring the
     user's data while guaranteeing the proven documentMap render path.
  2. Emits ONE coordinated, contract-correct gold-standard package (4 files) under
     ``gold_standard/economic_census_establishments_v1/``:

       economic_census_establishments_v1.template.blueprint.json  - analytic brain
       economic_census_establishments_v1.template.ast.json        - render skeleton
       economic_census_establishments_v1.semantic_slot_graph.json - slot wiring
       economic_census_establishments_v1.dataset.csv              - dense state data

The package is value-free + prose-free: structure, entities, executable question
contracts and slot lineage only. The S4-S6 generation pipeline (+ documentMap
bridge) fills it from the dataset. Discoverable on the binder start screen and
bindable with zero config (S0-S3.5 handoff ready).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd

TEMPLATE_ID = "tpl_economic_census_establishments_v1"
TEMPLATE_NAME = "Sixth Economic Census — Establishment & Employment Statistics"
VERSION = "1.0.0"
SLUG = "economic_census_establishments_v1"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "report_builder" / "gold_standard" / SLUG
SOURCE_XLSX = ROOT / "processed_dataset" / "analysis_30_processed.xlsx"
CENSUS_YEAR = "2013"  # Sixth Economic Census reference year (microdata coded 2005-series block)

# ── Geography: standard MoSPI region grouping ────────────────────────────────
REGION_STATES: dict[str, list[str]] = {
    "North": ["Delhi", "Haryana", "Punjab", "Rajasthan", "Himachal Pradesh",
              "Uttarakhand", "Jammu & Kashmir", "Chandigarh"],
    "South": ["Andhra Pradesh", "Karnataka", "Kerala", "Tamil Nadu", "Telangana",
              "Puducherry", "Lakshadweep", "Andaman & Nicobar Islands"],
    "East": ["Bihar", "Jharkhand", "Odisha", "West Bengal"],
    "West": ["Goa", "Gujarat", "Maharashtra", "Dadra & Nagar Haveli", "Daman & Diu"],
    "Central": ["Chhattisgarh", "Madhya Pradesh", "Uttar Pradesh"],
    "North-East": ["Assam", "Arunachal Pradesh", "Manipur", "Meghalaya", "Tripura",
                   "Sikkim", "Nagaland", "Mizoram"],
}
STATE_REGION = {s: r for r, states in REGION_STATES.items() for s in states}

# ── Entities (columnExpr MUST match the aggregated dataset header exactly) ────
DIMENSIONS = [
    ("ent_state_ut", "State/UT", "State/UT", None, "dimension"),
    ("ent_region", "Region", "Region", None, "dimension"),
    ("ent_census_year", "Census Year", "Census Year", "year", "time"),
]
# (entityId, entityName, columnExpr, unit)
MEASURES = [
    ("ent_establishments", "Establishments", "Establishments", "count"),
    ("ent_persons", "Persons Working", "Persons Working", "persons"),
    ("ent_female", "Female Workers", "Female Workers", "persons"),
    ("ent_child", "Child Workers", "Child Workers", "persons"),
    ("ent_hired", "Hired Workers", "Hired Workers", "persons"),
    ("ent_rural_estab", "Rural Establishments", "Rural Establishments", "count"),
    ("ent_urban_estab", "Urban Establishments", "Urban Establishments", "count"),
    ("ent_oae", "Own-Account Establishments", "Own Account Establishments", "count"),
    ("ent_hired_estab", "Establishments with Hired Workers", "Establishments with Hired Workers", "count"),
    ("ent_female_share", "Female Worker Share", "Female Share", "percent"),
    ("ent_hired_share", "Hired Worker Share", "Hired Share", "percent"),
    ("ent_child_share", "Child Worker Share", "Child Share", "percent"),
    ("ent_oae_share", "Own-Account Share", "OAE Share", "percent"),
    ("ent_urban_share", "Urban Establishment Share", "Urban Share", "percent"),
    ("ent_rural_share", "Rural Establishment Share", "Rural Share", "percent"),
    ("ent_avg_emp", "Average Employment", "Avg Employment", "persons"),
]
COL_OF = {eid: col for eid, _n, col, _u in MEASURES}
COL_OF.update({d[0]: d[2] for d in DIMENSIONS})
NAME_OF = {eid: n for eid, n, _c, _u in MEASURES}
NAME_OF.update({d[0]: d[1] for d in DIMENSIONS})
UNIT_OF = {eid: u for eid, _n, _c, u in MEASURES}

# ── Formula catalog ──────────────────────────────────────────────────────────
FORMULAS = [
    {"formulaId": "f_female_share", "formulaType": "SHARE", "label": "Female Worker Share",
     "numerator": "ent_female", "denominator": "ent_persons", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_hired_share", "formulaType": "SHARE", "label": "Hired Worker Share",
     "numerator": "ent_hired", "denominator": "ent_persons", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_child_share", "formulaType": "SHARE", "label": "Child Worker Share",
     "numerator": "ent_child", "denominator": "ent_persons", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 2},
    {"formulaId": "f_oae_share", "formulaType": "SHARE", "label": "Own-Account Establishment Share",
     "numerator": "ent_oae", "denominator": "ent_establishments", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_urban_share", "formulaType": "SHARE", "label": "Urban Establishment Share",
     "numerator": "ent_urban_estab", "denominator": "ent_establishments", "grain": "ent_state_ut",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_rural_share", "formulaType": "SHARE", "label": "Rural Establishment Share",
     "numerator": "ent_rural_estab", "denominator": "ent_establishments", "grain": "ent_region",
     "displayFormat": "percentage", "precision": 1},
    {"formulaId": "f_avg_employment", "formulaType": "RATIO", "label": "Average Employment per Establishment",
     "numerator": "ent_persons", "denominator": "ent_establishments", "grain": "ent_region",
     "displayFormat": "multiplier", "precision": 2},
]


# ── Question builders ────────────────────────────────────────────────────────

def rank_q(qid, title, intent, qtext, measure, chart_type, chart_title,
           *, grain="ent_state_ut", group_by="ent_region", top_n=12,
           table_cols=None, sort_order="descending", components=None, formula=None):
    return {
        "qid": qid, "title": title, "intent": intent, "qtext": qtext,
        "qtype": "ranking", "method": "DIRECT", "operation": "rank",
        "grain": grain, "measure": measure, "group_by": group_by,
        "sort_order": sort_order, "top_n": top_n,
        "table_cols": table_cols or [measure],
        "chart_type": chart_type, "chart_title": chart_title,
        "formula": formula,
        "components": components or ["narrative", "table", "chart"],
        "min_rows": 6, "max_rows": top_n,
    }


def comp_q(qid, title, intent, qtext, parts, whole, chart_type, chart_title,
           *, components=None):
    return {
        "qid": qid, "title": title, "intent": intent, "qtext": qtext,
        "qtype": "composition", "method": "DIRECT", "operation": "composition",
        "grain": "national", "parts": parts, "whole": whole, "measure": parts[0],
        "chart_type": chart_type, "chart_title": chart_title, "formula": None,
        "components": components or ["narrative", "chart"],
        "min_rows": 2, "max_rows": len(parts),
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


# ── The PLAN: 6 topics → 14 chapters → 26 sections → 26 questions ────────────
TOPICS: list[dict[str, Any]] = [
    {"tid": "topic_landscape", "title": "Establishment Landscape",
     "summary": "Where India's establishments are located — geographic spread, regional "
                "concentration and the rural–urban divide of the establishment base.",
     "chapters": [
        {"cid": "ch_geography", "title": "Geographic Distribution", "sections": [
            {"sid": "sec_state_estab", "title": "State-wise Establishment Ranking",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_state_estab", "Rank States/UTs by number of establishments",
                       "Identify which states anchor India's establishment base.",
                       "Rank States/UTs by the total number of enumerated establishments.",
                       "ent_establishments", "bar", "Establishments by State/UT",
                       table_cols=["ent_establishments", "ent_persons"])]},
            {"sid": "sec_region_estab", "title": "Regional Establishment Concentration",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_region_estab", "Aggregate establishments by region",
                       "Compare the establishment base across the six regions.",
                       "Aggregate the establishment count by region to show concentration.",
                       "ent_establishments", "pie", "Establishment Share by Region",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_rural_urban", "title": "Rural–Urban Spread", "sections": [
            {"sid": "sec_rural_urban", "title": "Rural vs Urban Establishments",
             "archetype": "composition", "questions": [
                comp_q("q_rural_urban", "Rural versus urban establishment split",
                       "Show the rural–urban composition of the establishment base.",
                       "What share of establishments operate in rural versus urban areas?",
                       ["ent_rural_estab", "ent_urban_estab"], "ent_establishments",
                       "donut", "Rural vs Urban Establishment Composition")]},
            {"sid": "sec_rural_lead", "title": "Rural Establishment Leaders",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_rural_lead", "Rank States/UTs by rural establishments",
                       "Locate the states where rural enterprise is most prevalent.",
                       "Rank States/UTs by the number of rural establishments.",
                       "ent_rural_estab", "bar", "Rural Establishments by State/UT")]},
            {"sid": "sec_urban_lead", "title": "Urban Establishment Leaders",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_urban_lead", "Rank States/UTs by urban establishments",
                       "Locate the states where urban enterprise concentrates.",
                       "Rank States/UTs by the number of urban establishments.",
                       "ent_urban_estab", "bar", "Urban Establishments by State/UT")]},
        ]},
        {"cid": "ch_urbanisation", "title": "Urbanisation of Enterprise", "sections": [
            {"sid": "sec_urban_share", "title": "Urban Establishment Share",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_urban_share", "Rank States/UTs by urban establishment share",
                        "Surface the most urbanised establishment economies.",
                        "Rank States/UTs by the urban share of all establishments.",
                        "ent_urban_share", "bar", "Urban Establishment Share by State/UT",
                        {"id": "f_urban_share", "type": "SHARE", "num": "ent_urban_estab",
                         "den": "ent_establishments", "grain": "ent_state_ut", "fmt": "percentage"},
                        grain="ent_state_ut", top_n=12,
                        components=["narrative", "table", "chart"])]},
            {"sid": "sec_rural_share_region", "title": "Rural Share by Region",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_rural_share_region", "Rank regions by rural establishment share",
                        "Compare the rurality of enterprise across regions.",
                        "Rank regions by the rural share of all establishments.",
                        "ent_rural_share", "bar", "Rural Establishment Share by Region",
                        {"id": "f_rural_share", "type": "SHARE", "num": "ent_rural_estab",
                         "den": "ent_establishments", "grain": "ent_region", "fmt": "percentage"},
                        grain="ent_region", top_n=6)]},
        ]},
     ]},
    {"tid": "topic_employment", "title": "Employment Generation",
     "summary": "The scale of employment generated by establishments — total persons engaged, "
                "regional employment aggregates and the average size of an establishment.",
     "chapters": [
        {"cid": "ch_emp_volume", "title": "Employment Volume", "sections": [
            {"sid": "sec_state_emp", "title": "State-wise Employment Ranking",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_state_emp", "Rank States/UTs by persons employed",
                       "Quantify the leading employment-generating states.",
                       "Rank States/UTs by the total number of persons usually working.",
                       "ent_persons", "bar", "Persons Working by State/UT",
                       table_cols=["ent_persons", "ent_establishments"])]},
            {"sid": "sec_region_emp", "title": "Regional Employment Aggregate",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_region_emp", "Aggregate employment by region",
                       "Compare total employment across the six regions.",
                       "Aggregate the persons usually working by region.",
                       "ent_persons", "bar", "Persons Working by Region",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_emp_scale", "title": "Establishment Scale", "sections": [
            {"sid": "sec_avg_emp", "title": "Average Employment per Establishment (Region)",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_avg_emp", "Rank regions by average employment per establishment",
                        "Compare establishment scale across regions.",
                        "Rank regions by the average number of persons per establishment.",
                        "ent_avg_emp", "bar", "Average Employment per Establishment by Region",
                        {"id": "f_avg_employment", "type": "RATIO", "num": "ent_persons",
                         "den": "ent_establishments", "grain": "ent_region", "fmt": "multiplier"},
                        grain="ent_region", top_n=6)]},
            {"sid": "sec_state_scale", "title": "Largest-Scale Establishment Economies",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_state_scale", "Rank States/UTs by average employment",
                       "Identify states whose establishments are larger on average.",
                       "Rank States/UTs by the average persons working per establishment.",
                       "ent_avg_emp", "bar", "Average Employment per Establishment by State/UT",
                       grain="ent_state_ut", top_n=12, sort_order="descending")]},
        ]},
     ]},
    {"tid": "topic_female", "title": "Women in the Workforce",
     "summary": "Female participation in establishment employment — the absolute count of "
                "women workers, their regional distribution and their share of the workforce.",
     "chapters": [
        {"cid": "ch_female_volume", "title": "Female Employment Volume", "sections": [
            {"sid": "sec_state_female", "title": "State-wise Female Workers",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_state_female", "Rank States/UTs by female workers",
                       "Quantify where women's establishment employment is largest.",
                       "Rank States/UTs by the number of female workers.",
                       "ent_female", "bar", "Female Workers by State/UT",
                       table_cols=["ent_female", "ent_persons"])]},
            {"sid": "sec_region_female", "title": "Regional Female Employment",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_region_female", "Aggregate female workers by region",
                       "Compare women's establishment employment across regions.",
                       "Aggregate the number of female workers by region.",
                       "ent_female", "bar", "Female Workers by Region",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_female_share", "title": "Female Participation Intensity", "sections": [
            {"sid": "sec_female", "title": "Female Worker Share by State",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_female_share", "Rank States/UTs by female worker share",
                        "Surface where women's participation in establishments is highest.",
                        "Rank States/UTs by the female share of persons working.",
                        "ent_female_share", "bar", "Female Worker Share by State/UT",
                        {"id": "f_female_share", "type": "SHARE", "num": "ent_female",
                         "den": "ent_persons", "grain": "ent_state_ut", "fmt": "percentage"},
                        grain="ent_state_ut", top_n=12,
                        components=["narrative", "table", "chart"])]},
            {"sid": "sec_female_region", "title": "Female Worker Share by Region",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_female_region", "Rank regions by female worker share",
                        "Compare women's participation across regions.",
                        "Rank regions by the female share of persons working.",
                        "ent_female_share", "bar", "Female Worker Share by Region",
                        {"id": "f_female_share", "type": "SHARE", "num": "ent_female",
                         "den": "ent_persons", "grain": "ent_region", "fmt": "percentage"},
                        grain="ent_region", top_n=6,
                        components=["narrative", "chart"])]},
        ]},
     ]},
    {"tid": "topic_labour", "title": "Labour Arrangements",
     "summary": "How establishments organise labour — reliance on hired workers versus "
                "self-employment, and the own-account character of the enterprise base.",
     "chapters": [
        {"cid": "ch_hired", "title": "Hired Labour", "sections": [
            {"sid": "sec_state_hired", "title": "State-wise Hired Workers",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_state_hired", "Rank States/UTs by hired workers",
                       "Quantify where wage labour in establishments concentrates.",
                       "Rank States/UTs by the number of hired workers.",
                       "ent_hired", "bar", "Hired Workers by State/UT",
                       table_cols=["ent_hired", "ent_persons"])]},
            {"sid": "sec_hired", "title": "Hired Worker Share by State",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_hired_share", "Rank States/UTs by hired worker share",
                        "Distinguish wage-labour economies from self-employment economies.",
                        "Rank States/UTs by the hired share of persons working.",
                        "ent_hired_share", "bar", "Hired Worker Share by State/UT",
                        {"id": "f_hired_share", "type": "SHARE", "num": "ent_hired",
                         "den": "ent_persons", "grain": "ent_state_ut", "fmt": "percentage"},
                        grain="ent_state_ut", top_n=12,
                        components=["narrative", "table", "chart"])]},
        ]},
        {"cid": "ch_self_employment", "title": "Self-Employment & Own-Account", "sections": [
            {"sid": "sec_type_mix", "title": "Own-Account vs Hired-Worker Establishments",
             "archetype": "composition", "questions": [
                comp_q("q_type_mix", "Own-account versus hired-worker establishment mix",
                       "Show the structural split between self-run and employer establishments.",
                       "What share of establishments are own-account versus those with hired workers?",
                       ["ent_oae", "ent_hired_estab"], "ent_establishments",
                       "pie", "Own-Account vs Hired-Worker Establishment Mix")]},
            {"sid": "sec_oae_share", "title": "Own-Account Establishment Share",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_oae_share", "Rank States/UTs by own-account share",
                        "Surface the most self-employment-driven establishment economies.",
                        "Rank States/UTs by the own-account share of all establishments.",
                        "ent_oae_share", "bar", "Own-Account Establishment Share by State/UT",
                        {"id": "f_oae_share", "type": "SHARE", "num": "ent_oae",
                         "den": "ent_establishments", "grain": "ent_state_ut", "fmt": "percentage"},
                        grain="ent_state_ut", top_n=12,
                        components=["narrative", "table", "chart"])]},
        ]},
     ]},
    {"tid": "topic_vulnerability", "title": "Vulnerability & Social Indicators",
     "summary": "Indicators of workforce vulnerability — the incidence of child workers in "
                "establishments, by state and region, flagged for policy attention.",
     "chapters": [
        {"cid": "ch_child_volume", "title": "Child Workers in Establishments", "sections": [
            {"sid": "sec_state_child", "title": "State-wise Child Workers",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_state_child", "Rank States/UTs by child workers",
                       "Flag states with the highest absolute child-worker counts.",
                       "Rank States/UTs by the number of child workers in establishments.",
                       "ent_child", "bar", "Child Workers by State/UT",
                       table_cols=["ent_child", "ent_persons"])]},
            {"sid": "sec_region_child", "title": "Regional Child-Worker Distribution",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_region_child", "Aggregate child workers by region",
                       "Compare child-worker incidence across regions.",
                       "Aggregate the number of child workers by region.",
                       "ent_child", "bar", "Child Workers by Region",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_child_share", "title": "Child-Worker Intensity", "sections": [
            {"sid": "sec_child_share", "title": "Child Worker Share by State",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_child_share", "Rank States/UTs by child worker share",
                        "Surface where child labour is most intense relative to the workforce.",
                        "Rank States/UTs by the child share of persons working.",
                        "ent_child_share", "bar", "Child Worker Share by State/UT",
                        {"id": "f_child_share", "type": "SHARE", "num": "ent_child",
                         "den": "ent_persons", "grain": "ent_state_ut", "fmt": "percentage"},
                        grain="ent_state_ut", top_n=12,
                        components=["narrative", "table", "chart"])]},
        ]},
     ]},
    {"tid": "topic_synthesis", "title": "Cross-Cutting Synthesis & Methodology",
     "summary": "A regional synthesis of the establishment economy, composite scale "
                "indicators, and the survey methodology, units and coverage for audit.",
     "chapters": [
        {"cid": "ch_regional_synthesis", "title": "Regional Synthesis", "sections": [
            {"sid": "sec_region_estab2", "title": "Regional Establishment Base",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_region_estab2", "Establishment base by region",
                       "Summarise the establishment base by region for synthesis.",
                       "Aggregate the establishment count by region (synthesis view).",
                       "ent_establishments", "bar", "Regional Establishment Base (Synthesis)",
                       grain="ent_region", group_by=None, top_n=6)]},
            {"sid": "sec_region_persons2", "title": "Regional Employment Base",
             "archetype": "ranking_distribution", "questions": [
                rank_q("q_region_persons2", "Employment base by region",
                       "Summarise the employment base by region for synthesis.",
                       "Aggregate the persons working by region (synthesis view).",
                       "ent_persons", "bar", "Regional Employment Base (Synthesis)",
                       grain="ent_region", group_by=None, top_n=6)]},
        ]},
        {"cid": "ch_composite", "title": "Composite Scale Indicators", "sections": [
            {"sid": "sec_region_scale", "title": "Average Establishment Scale by Region",
             "archetype": "ranking_distribution", "questions": [
                ratio_q("q_region_scale", "Average employment per establishment (synthesis)",
                        "Compare composite establishment scale across regions.",
                        "Rank regions by the average persons per establishment (synthesis).",
                        "ent_avg_emp", "bar", "Composite Establishment Scale by Region",
                        {"id": "f_avg_employment", "type": "RATIO", "num": "ent_persons",
                         "den": "ent_establishments", "grain": "ent_region", "fmt": "multiplier"},
                        grain="ent_region", top_n=6,
                        components=["narrative", "chart", "metric"])]},
        ]},
        {"cid": "ch_methodology", "title": "Data Provenance & Methodology", "sections": [
            {"sid": "sec_methodology", "title": "Sources, Units & Coverage",
             "archetype": "methodology", "questions": [
                {"qid": "q_methodology", "title": "Data sources and methodology",
                 "intent": "Document provenance, units and coverage for audit.",
                 "qtext": "What are the data sources, measurement units and coverage of this report?",
                 "qtype": "methodology", "method": "DIRECT", "operation": "metric",
                 "grain": "national", "measure": "ent_establishments", "chart_type": None,
                 "chart_title": None, "formula": None,
                 "components": ["methodology", "source_note", "glossary", "caveat"],
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


# ── Dataset: aggregate the REAL microdata to a dense state-level table ────────

DATASET_COLUMNS = [
    "State/UT", "Region", "Census Year", "Establishments", "Persons Working",
    "Female Workers", "Child Workers", "Hired Workers", "Rural Establishments",
    "Urban Establishments", "Own Account Establishments",
    "Establishments with Hired Workers", "Female Share", "Hired Share",
    "Child Share", "OAE Share", "Urban Share", "Rural Share", "Avg Employment",
]


def _clean_state(raw: str) -> str:
    s = str(raw).strip()
    return s


def _region_of(state: str) -> str:
    return STATE_REGION.get(state, "Other")


def build_dataset() -> list[dict[str, Any]]:
    """Read + clean + aggregate the real 6th Economic Census microdata to state grain."""
    df = pd.read_excel(SOURCE_XLSX)

    # Clean categorical whitespace / typo variants.
    df["State Ut"] = df["State Ut"].map(_clean_state)
    df["Location"] = df["Location"].astype(str).str.strip().str.title()
    df["Establishment Type"] = (
        df["Establishment Type"].astype(str).str.strip()
        .str.replace("Establisment", "Establishment", regex=False)
    )
    for col in ("Persons Usually Working", "Female Workers", "Child Workers", "Hired Workers"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    rows: list[dict[str, Any]] = []
    for state, g in df.groupby("State Ut"):
        region = _region_of(state)
        if region == "Other":
            continue  # keep the dense table to recognised States/UTs
        establishments = int(len(g))
        persons = int(g["Persons Usually Working"].sum())
        female = int(g["Female Workers"].sum())
        child = int(g["Child Workers"].sum())
        hired = int(g["Hired Workers"].sum())
        rural = int((g["Location"] == "Rural").sum())
        urban = int((g["Location"] == "Urban").sum())
        oae = int(g["Establishment Type"].str.startswith("Own Account").sum())
        hired_estab = int(g["Establishment Type"].str.contains("hired", case=False).sum())
        female_share = round(100.0 * female / persons, 1) if persons else 0.0
        hired_share = round(100.0 * hired / persons, 1) if persons else 0.0
        child_share = round(100.0 * child / persons, 2) if persons else 0.0
        oae_share = round(100.0 * oae / establishments, 1) if establishments else 0.0
        urban_share = round(100.0 * urban / establishments, 1) if establishments else 0.0
        rural_share = round(100.0 * rural / establishments, 1) if establishments else 0.0
        avg_emp = round(persons / establishments, 2) if establishments else 0.0
        rows.append({
            "State/UT": state, "Region": region, "Census Year": CENSUS_YEAR,
            "Establishments": establishments, "Persons Working": persons,
            "Female Workers": female, "Child Workers": child, "Hired Workers": hired,
            "Rural Establishments": rural, "Urban Establishments": urban,
            "Own Account Establishments": oae,
            "Establishments with Hired Workers": hired_estab,
            "Female Share": female_share, "Hired Share": hired_share,
            "Child Share": child_share, "OAE Share": oae_share,
            "Urban Share": urban_share, "Rural Share": rural_share,
            "Avg Employment": avg_emp,
        })
    rows.sort(key=lambda r: r["Establishments"], reverse=True)
    return rows


# ── Emit helpers (shared contract with the enterprise gold generators) ───────

def _req_entities(q):
    if q["operation"] == "composition":
        ids = [*q["parts"], q["whole"]]
    elif q["operation"] == "metric":
        ids = [q["measure"]]
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
            seen.add(e)
            out.append(e)
    return out


def _is_measure(eid: str) -> bool:
    return eid in COL_OF and eid not in ("ent_state_ut", "ent_region", "ent_census_year")


def _components(q):
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
                    "title": f"{NAME_OF[q['measure']]} by "
                             f"{NAME_OF.get(q['grain'], 'Group')}",
                    "rowEntity": q["grain"] if q["grain"].startswith("ent_") else "ent_state_ut",
                    "columns": cols, "groupRowsBy": q.get("group_by"),
                    "sortBy": q["measure"], "sortOrder": q.get("sort_order", "descending"),
                    "showRank": True, "unitLabel": UNIT_OF.get(q["measure"], ""),
                    "footnote": "Source: Sixth Economic Census, MoSPI",
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


# ── Emit: blueprint ──────────────────────────────────────────────────────────

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
                        "estimatedPageWeight": 1.1,
                        "requiredEntities": [
                            {"entityId": e, "role": ("measure" if _is_measure(e) else
                                                     ("time" if e == "ent_census_year" else "dimension")),
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
                        "provenanceRequirements": {"sourceAttribution": "Sixth Economic Census, MoSPI",
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
                    "sectionArchetype": s["archetype"], "pagePlan": {"estimatedPages": 1.1},
                    "questions": q_out})
            chapters_out.append({
                "chapterId": c["cid"], "title": c["title"], "order": len(chapters_out) + 1,
                "chapterType": "analytical", "officerSummary": c["title"],
                "pageBudget": {"min": 2, "max": 3}, "sections": sections_out})
        topics_out.append({
            "topicId": t["tid"], "title": t["title"], "order": len(topics_out) + 1,
            "semanticRef": t["tid"], "officerSummary": t["summary"],
            "pageBudget": {"min": 3, "max": 5}, "chapters": chapters_out})

    return {
        "$schema": "bharatstat/template-blueprint/v2",
        "contractVersion": "template.extraction.v2",
        "_doc": f"Enterprise analytic blueprint for {TEMPLATE_NAME}. "
                f"{len(TOPICS)} topics over the 6th Economic Census establishment base, "
                "state-level dense data aggregated from real microdata.",
        "templateMeta": {
            "templateId": TEMPLATE_ID, "name": TEMPLATE_NAME, "domain": "economic",
            "reportType": "enterprise_economic_census", "locale": "en-IN", "version": VERSION,
            "sourceDocument": "Sixth Economic Census of India — MoSPI",
            "valueFree": True, "proseFree": True, "targetPageCount": "30-38",
            "standardPageCount": 34, "hardPageCap": 44,
            "description": "Enterprise Economic Census report: establishment distribution, "
                           "rural-urban spread, employment volume, female participation, hired "
                           "labour reliance, establishment type mix and average scale.",
            "templateClass": "enterprise_publication", "releaseStage": "built_in_officer_ready",
            "createdBy": "BharatStat template architect", "lastUpdated": "2026-06-17",
            "compatibleStages": ["S0", "S1", "S2", "S3", "S3.5", "S4", "S5", "S6", "S7"],
        },
        "statisticalContext": {
            "sourceDocument": "Sixth Economic Census of India — MoSPI",
            "ministry": "Ministry of Statistics and Programme Implementation (MoSPI)",
            "domain": "economic", "geographyLevel": "state_ut", "regionMapping": REGION_STATES,
            "timeCoverage": [CENSUS_YEAR], "referenceDates": ["Sixth Economic Census reference period"],
            "dataSources": ["Sixth Economic Census", "Central Statistics Office",
                            "Directorate of Economics & Statistics (States)"],
            "footnotes": ["Establishment = unit engaged in production/distribution of goods/services "
                          "not for sole own consumption.",
                          "Own-account establishment = run without any hired worker on a regular basis."],
            "glossary": {
                "Establishment": "A unit engaged in production or distribution of goods or services "
                                 "not for the sole purpose of own consumption.",
                "Own-Account Establishment": "An establishment run without any hired worker on a "
                                             "fairly regular basis.",
                "Persons Usually Working": "Total persons usually working in the establishment, "
                                           "including the owner.",
                "Hired Worker": "A worker employed for wages/salary on a fairly regular basis.",
                "Female Worker Share": "Female workers as a percentage of all persons working.",
                "MoSPI": "Ministry of Statistics and Programme Implementation",
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
            "generatedFrom": "economic_census_establishments_v1_generator",
            "targetPageRange": "30-38", "standardPageCount": 34, "hardPageCap": 44,
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
        narr = _slot_id(q["qid"], "narrative") if "narrative" in q["components"] else None
        if narr:
            dep_on = [_slot_id(q["qid"], k) for k in q["components"] if k in ("table", "chart", "metric")]
            if dep_on:
                deps.append({"slot": narr, "dependsOn": dep_on, "reason": "Narrative cites the visual/metric"})
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
    qids = [q["qid"] for _t, _c, _s, q in all_questions()]
    assert len(qids) == len(set(qids)), "duplicate questionId"
    chart_titles = [q["chart_title"] for _t, _c, _s, q in all_questions() if q.get("chart_title")]
    dup = {x for x in chart_titles if chart_titles.count(x) > 1}
    assert not dup, f"OVERLAPPING CHART NAMES: {dup}"
    slot_ids = [s["slotId"] for s in emit_slot_graph()["slots"]]
    assert len(slot_ids) == len(set(slot_ids)), "duplicate slotId"
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
    print(f"OK  {TEMPLATE_ID}")
    print(f"  topics={n_topics} chapters={n_ch} sections={n_sec} questions={len(qids)}")
    print(f"  slots={len(slot_ids)} charts={len(chart_titles)} (all unique) entities={len(bp['entities'])}")
    print(f"  dataset: {len(rows)} States/UTs x {len(DATASET_COLUMNS)} cols (dense, from real microdata)")
    print(f"  -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
