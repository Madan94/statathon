"""Economics domain adapter for coordinate MultiAST (fina-ast layout).

Remaps energy-template copy to CPI/inflation, rebuilds tables and figure charts
from ``Economics - MoSPI.csv``, and attaches ``biQuery`` per body block for
Deep BI narrative generation.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from .schema import Figure, MultiAST, Paragraph, Table

logger = logging.getLogger(__name__)

_DATASET_DESC = (
    "MoSPI Consumer Price Index dataset with columns: indicator, base_year, year, "
    "month, state, index_al, index_rl, inflation_al, inflation_rl."
)

# Heading / title replacements (energy → economics, same section numbers)
_HEADING_MAP: dict[str, str] = {
    "Energy Reserves and Potential": "Consumer Price Index and Inflation",
    "CHAPTER 1: Energy Reserves and Potential": "CHAPTER 1: Consumer Price Index and Inflation",
    "Introduction": "Introduction",
    "Global Classification of Energy Reserves": "Measurement Framework for Consumer Price Index",
    "Energy Reserves in India": "Price Movements in India",
    "1.1 Coal Reserves": "1.1 General Price Index by State",
    "1.2 Lignite Reserves": "1.2 Inflation Rate (Year-on-Year) by State",
    "1.3 Crude Oil Reserves": "1.3 All-India Linking (AL) Index — Leading States",
    "1.4 Natural Gas Reserves": "1.4 Retail (RL) Inflation — Leading States",
    "1.5 Renewable Energy Potential in India": "1.5 Inflation Distribution Across States",
    "Geographical Distribution of Renewable Energy Potential": "Geographical Distribution of General Price Index",
}

_FIGURE_CAPTIONS: dict[str, str] = {
    "fig_001": "Fig 1.1: Share of States in National General Index (AL), January 2026",
    "fig_002": "Fig 1.2: Statewise Year-on-Year Inflation Rate (AL), January 2026",
    "fig_003": "Fig 1.3: Top States by General Index (AL), January 2026",
    "fig_004": "Fig 1.4: Top States by Year-on-Year Inflation (AL), January 2026",
    "fig_005": "Fig 1.5: Distribution of States by Inflation Band, January 2026",
    "fig_006": "Fig 1.6: Statewise General Index (AL), January 2026",
}

_TABLE_TITLES: dict[str, str] = {
    "table_001": "Table 1.1: Statewise General Index and Inflation (January 2026)",
    "table_002": "Table 1.2: States with Highest and Lowest Inflation (January 2026)",
    "table_003": "Table 1.3: All-India Monthly Index and Inflation (2025–2026)",
    "table_004": "Table 1.4: Top Ten States — Index and Inflation Summary (January 2026)",
}

_LIST_ITEMS = [
    "Headline index: General Index (base 2019=100).",
    "Current-linking series: index_al and inflation_al.",
    "Retail-linking series: index_rl and inflation_rl.",
]

# Per-paragraph BI queries (templateQuestion = old body text at remap time)
_BODY_QUERIES: dict[str, str] = {
    "p_006": "Explain what the Consumer Price Index measures in India and how index_al and inflation_al should be read. Use only facts from the dataset.",
    "p_007": "Clarify how CPI compilation depends on the reference period and linking methodology (AL vs RL). Ground in available columns.",
    "p_009": "Describe the official CPI framework (base year, linking) as applicable to this General Index series. No invented statistics.",
    "p_010": "Summarise how economic viability and field feasibility relate to CPI field operations (enumeration, coverage). Use dataset scope only.",
    "p_012": "Describe the diversity of price movements across Indian states in the latest January 2026 snapshot: range of index_al and inflation_al.",
    "p_013": "Discuss how inflation differs across states in January 2026; cite top and bottom states by inflation_al with exact values.",
    "p_014": "Write a chapter overview for CPI: cover index levels, inflation, and geographic concentration using January 2026 data only.",
    "p_016": "Replace the coal reserves paragraph: report All-India General Index (AL) in January 2026 and change vs prior month if visible in data.",
    "p_017": "Report year-on-year inflation (inflation_al) for All India in January 2026 and compare to the June 2025 reading if present.",
    "p_018": "Which three states have the highest index_al in January 2026 and what share of the sum of state indices do they represent?",
    "p_021": "Report All-India index_al in January 2026 and the month-on-month change from December 2025 if available in the dataset.",
    "p_022": "Which states lead on index_al in January 2026 and what percentage of the all-state total index do the top two represent?",
    "p_024": "Report All-India inflation_al in January 2026 and whether it rose or fell versus June 2025.",
    "p_025": "Which states have the highest and lowest inflation_al in January 2026? Give exact percentages.",
    "p_027": "Summarise the spread of inflation_al across states in January 2026 (max, min, All India).",
    "p_028": "Describe how inflation is distributed across states (high/moderate/low bands) for January 2026 referencing Table 1.4 and Fig 1.5.",
    "p_029": "Discuss states with inflation_al above 3% in January 2026 — list them with values.",
    "p_030": "Discuss states with inflation_al between 1% and 3% in January 2026.",
    "p_031": "Discuss states with inflation_al below 1% or negative in January 2026.",
    "p_032": "Comment on small states and UTs with distinctive index_al in January 2026.",
    "p_033": "Compare index_al and index_rl for states where both are available in January 2026.",
    "p_034": "Note any states with zero or missing index_al in January 2026 and how RL series behaves.",
    "p_036": "List the five states with highest index_al in January 2026 and their index values.",
    "p_037": "What percentage of the sum of state index_al values do the top five states account for in January 2026?",
}


def _latest_period(df: pd.DataFrame) -> tuple[str, str]:
    work = df.copy()
    work["_y"] = work["year"].astype(str)
    work["_m"] = work["month"].astype(str)
    # Prefer calendar 2026 January
    if ((work["_y"] == "2026") & (work["_m"] == "January")).any():
        return "2026", "January"
    grp = work.groupby(["_y", "_m"]).size().reset_index(name="n")
    grp = grp.sort_values(["_y", "_m"], ascending=[False, False])
    row = grp.iloc[0]
    return str(row["_y"]), str(row["_m"])


def _period_slice(df: pd.DataFrame, year: str, month: str) -> pd.DataFrame:
    m = (
        (df["year"].astype(str) == year)
        & (df["month"].astype(str) == month)
        & (df["state"].astype(str) != "All India")
    )
    sub = df.loc[m].copy()
    for c in ("index_al", "index_rl", "inflation_al", "inflation_rl"):
        sub[c] = pd.to_numeric(sub[c], errors="coerce").fillna(0)
    return sub


def _all_india_row(df: pd.DataFrame, year: str, month: str) -> pd.Series | None:
    m = (
        (df["year"].astype(str) == year)
        & (df["month"].astype(str) == month)
        & (df["state"].astype(str) == "All India")
    )
    rows = df.loc[m]
    if rows.empty:
        return None
    return rows.iloc[0]


def collect_economics_facts(df: pd.DataFrame) -> dict[str, Any]:
    year, month = _latest_period(df)
    snap = _period_slice(df, year, month)
    ai = _all_india_row(df, year, month)
    facts: dict[str, Any] = {
        "dataset_type": "economic",
        "reference_period": f"{month} {year}",
        "indicator": "General Index",
        "base_year": "2019",
        "state_count": int(snap["state"].nunique()),
    }
    if ai is not None:
        facts["all_india_index_al"] = round(float(ai["index_al"]), 2)
        facts["all_india_index_rl"] = round(float(ai["index_rl"]), 2)
        facts["all_india_inflation_al"] = round(float(ai["inflation_al"]), 2)
        facts["all_india_inflation_rl"] = round(float(ai["inflation_rl"]), 2)
    if not snap.empty:
        top_idx = snap.sort_values("index_al", ascending=False).iloc[0]
        bot_idx = snap.sort_values("index_al", ascending=True).iloc[0]
        top_inf = snap.sort_values("inflation_al", ascending=False).iloc[0]
        bot_inf = snap.sort_values("inflation_al", ascending=True).iloc[0]
        facts.update({
            "top_state_index_al": str(top_idx["state"]),
            "top_state_index_al_value": round(float(top_idx["index_al"]), 2),
            "bottom_state_index_al": str(bot_idx["state"]),
            "bottom_state_index_al_value": round(float(bot_idx["index_al"]), 2),
            "top_state_inflation_al": str(top_inf["state"]),
            "top_state_inflation_al_value": round(float(top_inf["inflation_al"]), 2),
            "bottom_state_inflation_al": str(bot_inf["state"]),
            "bottom_state_inflation_al_value": round(float(bot_inf["inflation_al"]), 2),
            "mean_index_al": round(float(snap["index_al"].mean()), 2),
            "mean_inflation_al": round(float(snap["inflation_al"].mean()), 2),
        })
        top3 = snap.nlargest(3, "index_al")
        facts["top3_states_index"] = top3["state"].tolist()
        facts["top3_index_values"] = [round(float(v), 2) for v in top3["index_al"]]
        total_idx = float(snap["index_al"].sum()) or 1.0
        facts["top3_index_share_pct"] = round(
            float(top3["index_al"].sum()) / total_idx * 100, 1
        )
    return facts


def _build_tables(ast: MultiAST, df: pd.DataFrame) -> None:
    year, month = _latest_period(df)
    snap = _period_slice(df, year, month).sort_values("index_al", ascending=False)
    ai = _all_india_row(df, year, month)

    def _set(tid: str, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        t = ast.tableAST.by_id(tid)
        if not t:
            return
        t.title = title
        t.columns = columns
        t.rows = rows

    # Table 1.1 — all states
    rows_1: list[list[Any]] = []
    for _, r in snap.iterrows():
        rows_1.append([
            r["state"],
            f"{r['index_al']:.2f}",
            f"{r['index_rl']:.2f}",
            f"{r['inflation_al']:.2f}",
            f"{r['inflation_rl']:.2f}",
        ])
    if ai is not None:
        rows_1.append([
            "All India",
            f"{float(ai['index_al']):.2f}",
            f"{float(ai['index_rl']):.2f}",
            f"{float(ai['inflation_al']):.2f}",
            f"{float(ai['inflation_rl']):.2f}",
        ])
    _set("table_001", _TABLE_TITLES["table_001"],
         ["States/UTs", "Index (AL)", "Index (RL)", "Inflation AL (%)", "Inflation RL (%)"],
         rows_1)

    # Table 1.2 — top/bottom 5 inflation
    by_inf = snap.sort_values("inflation_al", ascending=False)
    rows_2: list[list[Any]] = []
    for _, r in pd.concat([by_inf.head(5), by_inf.tail(5)]).iterrows():
        rows_2.append([r["state"], f"{r['inflation_al']:.2f}", f"{r['index_al']:.2f}"])
    _set("table_002", _TABLE_TITLES["table_002"],
         ["States/UTs", "Inflation AL (%)", "Index (AL)"], rows_2)

    # Table 1.3 — All India monthly
    ai_rows = df[df["state"].astype(str) == "All India"].copy()
    ai_rows["_y"] = ai_rows["year"].astype(str)
    ai_rows["_m"] = ai_rows["month"].astype(str)
    ai_rows = ai_rows.sort_values(["_y", "_m"])
    recent = ai_rows.tail(12)
    rows_3 = [
        [str(r["month"]), str(r["year"]),
         f"{float(r['index_al']):.2f}", f"{float(r['inflation_al']):.2f}"]
        for _, r in recent.iterrows()
    ]
    _set("table_003", _TABLE_TITLES["table_003"],
         ["Month", "Year", "All India Index (AL)", "Inflation AL (%)"], rows_3)

    # Table 1.4 — top 10 states
    top10 = snap.head(10)
    rows_4 = [
        [r["state"], f"{r['index_al']:.2f}", f"{r['inflation_al']:.2f}",
         f"{float(r['index_al']) / float(snap['index_al'].sum()) * 100:.2f}"]
        for _, r in top10.iterrows()
    ]
    _set("table_004", _TABLE_TITLES["table_004"],
         ["States/UTs", "Index (AL)", "Inflation AL (%)", "Share of State Index (%)"],
         rows_4)


def _inflation_bands(snap: pd.DataFrame) -> list[dict[str, Any]]:
    high = snap[snap["inflation_al"] > 3]
    mod = snap[(snap["inflation_al"] >= 1) & (snap["inflation_al"] <= 3)]
    low = snap[snap["inflation_al"] < 1]
    return [
        {"label": "High (>3%)", "value": float(len(high))},
        {"label": "Moderate (1–3%)", "value": float(len(mod))},
        {"label": "Low (<1%)", "value": float(len(low))},
    ]


def _build_figures(ast: MultiAST, df: pd.DataFrame) -> None:
    year, month = _latest_period(df)
    snap = _period_slice(df, year, month)
    total_idx = float(snap["index_al"].sum()) or 1.0

    charts: dict[str, dict[str, Any]] = {}

    # Fig 1.1 — pie: top 5 states share of index + Others
    top5 = snap.nlargest(5, "index_al")
    others = total_idx - float(top5["index_al"].sum())
    data_1 = [
        {"label": str(r["state"]), "value": round(float(r["index_al"]) / total_idx * 100, 1)}
        for _, r in top5.iterrows()
    ]
    if others > 0:
        data_1.append({"label": "Other States", "value": round(others / total_idx * 100, 1)})
    charts["fig_001"] = {"type": "pie", "data": data_1}

    # Fig 1.2 — pie: inflation bands
    charts["fig_002"] = {"type": "pie", "data": _inflation_bands(snap)}

    # Fig 1.3 — bar: top states index_al
    top8_idx = snap.nlargest(8, "index_al")
    charts["fig_003"] = {
        "type": "bar",
        "data": [{"label": str(r["state"]), "value": float(r["index_al"])}
                 for _, r in top8_idx.iterrows()],
    }

    # Fig 1.4 — bar: top states inflation_al
    top8_inf = snap.nlargest(8, "inflation_al")
    charts["fig_004"] = {
        "type": "bar",
        "data": [{"label": str(r["state"]), "value": float(r["inflation_al"])}
                 for _, r in top8_inf.iterrows()],
    }

    # Fig 1.5 — pie: inflation bands (same as 1.2 layout slot)
    charts["fig_005"] = {"type": "pie", "data": _inflation_bands(snap)}

    # Fig 1.6 — bar: top 8 index (statewise potential analogue)
    charts["fig_006"] = charts["fig_003"]

    for fig in ast.figureAST.figures:
        cap = _FIGURE_CAPTIONS.get(fig.figureId)
        if cap:
            fig.caption = cap
        spec = charts.get(fig.figureId)
        if spec:
            fig.computed_chart = {
                "type": spec["type"],
                "title": fig.caption,
                "data": spec["data"],
            }


def _remap_paragraphs(ast: MultiAST) -> None:
    for para in ast.contentAST.paragraphs:
        if para.content in _HEADING_MAP:
            para.content = _HEADING_MAP[para.content]
        elif para.type in ("heading_1", "heading_2", "chapter_header", "subtitle"):
            for old, new in _HEADING_MAP.items():
                if old in para.content:
                    para.content = para.content.replace(old, new)
        if para.type == "body" and para.id in _BODY_QUERIES:
            para.templateQuestion = para.content
            para.biQuery = (
                f"{_BODY_QUERIES[para.id]} Context: {_DATASET_DESC} "
                f"Template section text to replace: {para.templateQuestion[:400]}"
            )
    for lst in ast.contentAST.lists:
        if lst.id == "l_001":
            lst.items = list(_LIST_ITEMS)


def fallback_body_text(para_id: str, facts: dict[str, Any]) -> str:
    """Grounded MoSPI-style paragraph when Gemini / Deep BI narrative is empty."""
    period = facts.get("reference_period", "the latest period")
    ai_idx = facts.get("all_india_index_al")
    ai_inf = facts.get("all_india_inflation_al")
    top_s = facts.get("top_state_index_al")
    top_v = facts.get("top_state_index_al_value")
    top3 = facts.get("top3_states_index") or []
    top3_share = facts.get("top3_index_share_pct")
    hi_inf = facts.get("top_state_inflation_al")
    hi_inf_v = facts.get("top_state_inflation_al_value")
    lo_inf = facts.get("bottom_state_inflation_al")
    lo_inf_v = facts.get("bottom_state_inflation_al_value")

    def _fmt(v: Any, suffix: str = "") -> str:
        if v is None:
            return "(data unavailable)"
        return f"{v}{suffix}"

    def _pct(v: Any) -> str:
        if v is None:
            return "(data unavailable)"
        return f"{v}%"

    templates: dict[str, str] = {
        "p_006": (
            f"The Consumer Price Index (General Index, base 2019=100) measures average price "
            f"movements at the state and all-India level. For {period}, the all-India index (AL) "
            f"stood at {_fmt(ai_idx)} with year-on-year inflation (AL) of {_pct(ai_inf)}."
        ),
        "p_012": (
            f"Price levels in {period} varied across {facts.get('state_count', 34)} states/UTs. "
            f"The highest index (AL) was recorded in {top_s} ({_fmt(top_v)}), while the "
            f"all-India index was {_fmt(ai_idx)}."
        ),
        "p_013": (
            f"Inflation (AL) in {period} ranged from {_pct(lo_inf_v)} in {lo_inf} to "
            f"{_pct(hi_inf_v)} in {hi_inf}. The all-India inflation rate was "
            f"{_pct(ai_inf)}."
        ),
        "p_014": (
            f"This chapter summarises CPI movements for {period}: all-India index (AL) "
            f"{_fmt(ai_idx)}, inflation (AL) {_pct(ai_inf)}, and concentration of "
            f"high index values among leading states."
        ),
        "p_016": (
            f"As of {period}, the all-India General Index (AL) was {_fmt(ai_idx)} with "
            f"year-on-year inflation of {_pct(ai_inf)} (Table 1.1)."
        ),
        "p_017": (
            f"Year-on-year inflation (AL) for All India in {period} was {_pct(ai_inf)}."
        ),
        "p_018": (
            f"The index (AL) is concentrated in a few states. In {period}, "
            f"{', '.join(top3[:3]) if top3 else 'leading states'} "
            f"together accounted for about {_pct(top3_share)} of the sum of state indices "
            f"(Figure 1.1)."
        ),
        "p_021": (
            f"In {period}, the all-India index (AL) was {_fmt(ai_idx)} (Table 1.3)."
        ),
        "p_022": (
            f"Among states, {top_s} recorded the highest index (AL) at {_fmt(top_v)} in {period} "
            f"(Figure 1.3)."
        ),
        "p_024": (
            f"All-India inflation (AL) in {period} was {_pct(ai_inf)}."
        ),
        "p_025": (
            f"{hi_inf} reported the highest inflation (AL) at {_pct(hi_inf_v)}, while "
            f"{lo_inf} had the lowest at {_pct(lo_inf_v)} (Figure 1.4)."
        ),
        "p_027": (
            f"Across states in {period}, mean inflation (AL) was "
            f"{_pct(facts.get('mean_inflation_al'))} against the all-India rate of "
            f"{_pct(ai_inf)}."
        ),
        "p_036": (
            f"States with the highest index (AL) in {period} include "
            f"{', '.join(top3[:5]) if top3 else top_s} (Figure 1.6)."
        ),
        "p_037": (
            f"The top five states by index (AL) accounted for a substantial share of the "
            f"combined state index total in {period} (see Table 1.4)."
        ),
    }
    if para_id in templates:
        return templates[para_id]
    return (
        f"For {period}, the all-India General Index (AL) was {_fmt(ai_idx)} and inflation "
        f"(AL) was {_pct(ai_inf)}, with {top_s} leading among states on index level."
    )


def apply_economics_domain(ast: MultiAST, df: pd.DataFrame) -> dict[str, Any]:
    """Remap energy template → economics; rebuild tables/figures from CSV."""
    _remap_paragraphs(ast)
    _build_tables(ast, df)
    _build_figures(ast, df)
    facts = collect_economics_facts(df)
    logger.info(
        "Economics domain applied: period=%s states=%s",
        facts.get("reference_period"),
        facts.get("state_count"),
    )
    return facts
