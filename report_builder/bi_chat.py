"""Business Intelligence chat — runs inside the canvas while editing a report.

Each user query flows through the same 6-phase machinery:

  Phase 1 (KG)         — Cypher / n10s lookup if the query references entities
                         already in the Neo4j projection (e.g. 'show columns
                         that influence X')
  Phase 2 (Memory)     — STM holds the chat turns for this job; LTM (Qdrant
                         vector store of MoSPI reflections) is queried for
                         methodological grounding.
  Phase 3 (Kernel)     — Semantic Router classifies intent:
                          * deterministic_sql -> DuckDB over Arrow Table
                          * python_kernel     -> pandas / scipy operations
                          * narrative         -> Phase 4 Scribe
  Phase 4 (Firewall)   — Scribe (Gemini) drafts the answer; Verifier recomputes
                         every numeric claim before the answer is surfaced.
  Phase 5 (AGUI)       — Result is packaged as a `RenderedBlock` so it can be
                         dragged from the chat pane into any section of the
                         report canvas without a separate transform.

The returned object is therefore *identical in shape* to a regular report block,
so the drop handler on the frontend simply appends it to the target section.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from . import firewall as fw
from . import kernel as kx
from .agui import RenderedBlock
from .memory import ReflectionLedger, STM

logger = logging.getLogger(__name__)


# ---------------- Public entry ----------------

@dataclass
class ChatTurn:
    role: str            # 'user' | 'assistant'
    text: str
    block: dict[str, Any] | None = None   # RenderedBlock.to_dict() if any
    route: dict[str, Any] | None = None   # semantic router decision
    verifier: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "block": self.block,
            "route": self.route,
            "verifier": self.verifier,
            "created_at": self.created_at,
        }


def chat_query(
    *,
    job_id: int,
    analysis_id: int,
    query: str,
    analysis_payload: dict[str, Any],
    df_loader: Callable[[], pd.DataFrame],
    ledger: ReflectionLedger | None = None,
    stm: STM | None = None,
) -> ChatTurn:
    """Run one user turn through Phases 1-5 and return a RenderedBlock-shaped answer."""
    stm = stm or STM()
    history = stm.get(job_id, "chat_history") or []

    # Phase 3 — get the live DataFrame (cached in the Arrow kernel)
    df: pd.DataFrame
    try:
        df = kx.ensure_loaded(analysis_id, df_loader)
    except Exception as exc:
        logger.info("Chat: df load failed (%s); proceeding with payload-only mode", exc)
        df = pd.DataFrame()

    # Phase 3 — Semantic Router
    intent = _classify_chat_intent(query)
    route = {"engine": intent.kind, "rationale": intent.rationale}

    # Phase 1 — KG lookup hooks for relational intents
    kg_facts = _kg_lookup(query, analysis_payload)

    # Phase 2 — Retrieve grounding reflections from LTM
    reflections = []
    if ledger:
        reflections = ledger.retrieve_similar("bi_chat", query, limit=3)

    # Route to the right engine
    if intent.kind == "sql" and not df.empty:
        block_dict, narrative = _answer_via_sql(query, df)
    elif intent.kind == "stats" and not df.empty:
        block_dict, narrative = _answer_via_stats(query, df, analysis_payload)
    elif intent.kind == "kg":
        block_dict, narrative = _answer_via_kg(query, kg_facts, analysis_payload)
    else:
        block_dict, narrative = _answer_via_narrative(
            query, analysis_payload, kg_facts, reflections,
        )

    # Phase 4 — Verifier
    verdict = fw.verify_block(
        block_id=block_dict.get("block_id", "chat_block"),
        narrative=narrative or block_dict.get("payload", {}).get("text", ""),
        df=df if not df.empty else None,
        expected_facts=_facts_for_verifier(analysis_payload, df),
    )
    block_dict["verifier"] = verdict.to_dict()

    turn = ChatTurn(
        role="assistant",
        text=narrative or "(no narrative — table/chart result)",
        block=block_dict,
        route=route,
        verifier=verdict.to_dict(),
    )

    history.append({"role": "user", "text": query, "created_at": datetime.utcnow().isoformat()})
    history.append(turn.to_dict())
    stm.put(job_id, "chat_history", history)
    return turn


def get_history(job_id: int, stm: STM | None = None) -> list[dict[str, Any]]:
    stm = stm or STM()
    return stm.get(job_id, "chat_history") or []


# ---------------- Intent classification (Phase 3 router) ----------------

@dataclass
class _ChatIntent:
    kind: str   # 'sql' | 'stats' | 'kg' | 'narrative'
    rationale: str


_SQL_TRIGGERS = ("count", "how many", "group by", "average", "mean of",
                 "sum of", "filter where", "top ", "bottom ")
_STATS_TRIGGERS = ("outlier", "anomaly", "z-score", "iqr", "missing", "skew",
                   "correlation", "corr between")
_KG_TRIGGERS = ("influence", "depends on", "related to", "cluster",
                "semantic domain", "dependency", "graph", "neighbours", "neighbors")


def _classify_chat_intent(query: str) -> _ChatIntent:
    q = query.lower()
    if any(t in q for t in _KG_TRIGGERS):
        return _ChatIntent("kg", "graph relationship lookup")
    if any(t in q for t in _STATS_TRIGGERS):
        return _ChatIntent("stats", "deterministic statistics in Python kernel")
    if any(t in q for t in _SQL_TRIGGERS):
        return _ChatIntent("sql", "DuckDB SQL over Arrow Table")
    return _ChatIntent("narrative", "Scribe (Gemini) under Firewall constraints")


# ---------------- Engines ----------------

def _answer_via_sql(query: str, df: pd.DataFrame) -> tuple[dict[str, Any], str]:
    """Try to compile the user query to a SQL statement and run it via DuckDB.

    Falls back to a small descriptive narrative if Gemini-to-SQL fails.
    """
    sql = _user_query_to_sql(query, df)
    if not sql:
        return _answer_via_narrative(query, {"row_count": int(len(df))}, {}, [])

    try:
        result = kx.run_sql(df, sql)
    except Exception as exc:
        return _answer_via_narrative(
            f"{query}\n[SQL attempt: {sql}]",
            {"row_count": int(len(df)), "error": str(exc)}, {}, [],
        )

    cols = [str(c) for c in result.columns]
    rows = result.head(60).to_dict(orient="records")
    block = _make_block(
        block_id=_chat_block_id(),
        kind="table",
        title=_short_title(query),
        section="bi_findings",
        payload={"columns": cols, "rows": rows, "sql": sql},
    )
    narrative = f"Returned {len(rows)} rows. SQL used: {sql}"
    return block, narrative


def _answer_via_stats(query: str, df: pd.DataFrame,
                      payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    q = query.lower()
    if "missing" in q:
        counts = kx.column_missing_counts(df)
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:15]
        top = [(k, v) for k, v in top if v > 0]
        if not top:
            return (
                _make_block(_chat_block_id(), "metric", _short_title(query),
                            "bi_findings", payload={"metrics": {"missing": 0}}),
                "No missing values detected across columns.",
            )
        block = _make_block(
            _chat_block_id(), "chart", _short_title(query), "bi_findings",
            payload={"chart_type": "bar", "title": "Missing per column",
                     "labels": [k for k, _ in top], "values": [v for _, v in top]},
        )
        return block, f"Missing values concentrated in {len(top)} columns."
    if "outlier" in q or "anomaly" in q or "z-score" in q:
        counts = kx.count_outliers_zscore(df)
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:15]
        top = [(k, v) for k, v in top if v > 0]
        if not top:
            return (
                _make_block(_chat_block_id(), "metric", _short_title(query),
                            "bi_findings", payload={"metrics": {"outliers": 0}}),
                "No |z|>3 outliers detected.",
            )
        block = _make_block(
            _chat_block_id(), "chart", _short_title(query), "bi_findings",
            payload={"chart_type": "bar", "title": "Z-score outliers per column",
                     "labels": [k for k, _ in top], "values": [v for _, v in top]},
        )
        return block, f"{sum(v for _, v in top)} candidate outliers across {len(top)} columns."
    if "corr" in q:
        numeric = df.select_dtypes(include="number")
        if numeric.shape[1] < 2:
            return _answer_via_narrative(query, {"reason": "needs >=2 numeric cols"}, {}, [])
        corr = numeric.corr().abs().stack().reset_index()
        corr.columns = ["a", "b", "abs_corr"]
        corr = corr[corr["a"] < corr["b"]].sort_values("abs_corr", ascending=False).head(20)
        block = _make_block(
            _chat_block_id(), "table", _short_title(query), "bi_findings",
            payload={"columns": ["a", "b", "abs_corr"],
                     "rows": corr.to_dict(orient="records")},
        )
        return block, f"Top {len(corr)} correlation pairs by |r|."

    # Generic numeric stats
    stats = kx.column_numeric_stats(df)
    rows = [{"column": k, **v} for k, v in stats.items()]
    block = _make_block(
        _chat_block_id(), "table", _short_title(query), "bi_findings",
        payload={"columns": ["column", "min", "max", "mean", "median", "std", "count"],
                 "rows": rows},
    )
    return block, "Numeric column profile."


def _answer_via_kg(query: str, kg_facts: dict[str, Any],
                   payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    deps = kg_facts.get("dependencies") or {}
    edges = kg_facts.get("edges") or []
    if edges:
        labels = [f"{e.get('source')}->{e.get('target')}" for e in edges[:15]]
        values = [float(e.get("weight") or 0) for e in edges[:15]]
        block = _make_block(
            _chat_block_id(), "chart", _short_title(query), "bi_findings",
            payload={"chart_type": "bar", "title": "Schema graph edges",
                     "labels": labels, "values": values},
        )
        return block, f"Top {len(labels)} dependency edges by weight."
    if deps:
        rows = [{"column": col, "depends_on": d.get("column"),
                 "score": d.get("score")}
                for col, items in deps.items()
                for d in (items or [])[:5]]
        block = _make_block(
            _chat_block_id(), "table", _short_title(query), "bi_findings",
            payload={"columns": ["column", "depends_on", "score"], "rows": rows},
        )
        return block, f"{len(rows)} dependency relations resolved from Knowledge Graph."
    return _answer_via_narrative(query, payload, kg_facts, [])


def _answer_via_narrative(
    query: str, payload: dict[str, Any], kg_facts: dict[str, Any],
    reflections: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    facts = _facts_for_verifier(payload, None)
    facts["kg"] = {"summary": kg_facts.get("summary")} if kg_facts else {}
    text = fw.scribe_narrative(
        block_id="bi_chat",
        block_title=_short_title(query),
        block_section="bi_findings",
        hints={"max_words": 200, "tone": "analyst, conversational"},
        facts={"query": query, **facts},
        reflections=reflections,
    )
    block = _make_block(_chat_block_id(), "narrative", _short_title(query),
                        "bi_findings", payload={"text": text})
    return block, text


# ---------------- KG access (Phase 1 hook) ----------------

def _kg_lookup(query: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Pull edges / dependencies relevant to the question from the analysis payload.

    In production this calls Neo4j (n10s) for Cypher patterns; locally we read
    the same data straight off the analysis payload that built the projection.
    """
    sg = payload.get("schema_graph") or {}
    deps = payload.get("priority_dependencies") or {}
    return {
        "edges": (sg.get("edges") if isinstance(sg, dict) else []) or [],
        "dependencies": deps if isinstance(deps, dict) else {},
        "summary": {
            "edge_count": len(sg.get("edges") or []) if isinstance(sg, dict) else 0,
            "dependency_count": sum(len(v or []) for v in (deps.values() if isinstance(deps, dict) else [])),
        },
    }


# ---------------- Helpers ----------------

_SQL_CHAR_OK = re.compile(r"[A-Za-z0-9_]+")


def _user_query_to_sql(query: str, df: pd.DataFrame) -> str | None:
    """Very small Gemini-free SQL compiler for common patterns; returns None if unsupported.

    Patterns handled:
      * 'count of X by Y'
      * 'average of X by Y'
      * 'top N by X'
    Anything else returns None and falls through to narrative.
    """
    q = query.lower()
    cols = {c.lower(): c for c in df.columns}

    m = re.search(r"count of (\w+) by (\w+)", q)
    if m and m.group(1) in cols and m.group(2) in cols:
        return f'SELECT "{cols[m.group(2)]}" AS group_value, COUNT("{cols[m.group(1)]}") AS cnt FROM df GROUP BY 1 ORDER BY cnt DESC LIMIT 50'
    m = re.search(r"(average|mean) of (\w+) by (\w+)", q)
    if m and m.group(2) in cols and m.group(3) in cols:
        return f'SELECT "{cols[m.group(3)]}" AS group_value, AVG("{cols[m.group(2)]}") AS avg_value FROM df GROUP BY 1 ORDER BY avg_value DESC LIMIT 50'
    m = re.search(r"top (\d+) by (\w+)", q)
    if m and m.group(2) in cols:
        n = max(1, min(int(m.group(1)), 200))
        return f'SELECT * FROM df ORDER BY "{cols[m.group(2)]}" DESC LIMIT {n}'
    return None


def _make_block(block_id: str, kind: str, title: str, section: str,
                payload: dict[str, Any]) -> dict[str, Any]:
    return RenderedBlock(
        block_id=block_id,
        kind=kind,
        title=title,
        section=section,
        payload=payload,
        route={"engine": "bi_chat", "rationale": "user-driven exploration"},
        version=1,
    ).to_dict()


def _short_title(query: str) -> str:
    t = query.strip().rstrip("?").rstrip(".")
    if len(t) > 80:
        t = t[:77] + "…"
    return t[:1].upper() + t[1:] if t else "Chat result"


def _chat_block_id() -> str:
    return f"chat_{int(datetime.utcnow().timestamp() * 1000)}"


def _facts_for_verifier(payload: dict[str, Any], df: pd.DataFrame | None) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    health = (payload.get("health") or {})
    for k in ("row_count", "column_count", "missing_pct"):
        if k in health:
            facts[k] = health[k]
    if df is not None and not df.empty:
        facts.setdefault("row_count", int(len(df)))
        facts.setdefault("column_count", int(len(df.columns)))
    return facts
