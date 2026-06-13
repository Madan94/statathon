"""S1 — Entity → column resolver (proposal stage).

Consumes blueprint entities (``canonicalName`` + ``aliases`` + ``valueDomain``)
and a :class:`DatasetAST`, then proposes an :class:`EntityBinding` per entity:

  * **cascade scoring** — exact → alias → synonym/token → embedding (offline-skip),
    reusing :class:`deep_bi.column_synonym_kg.ColumnSynonymKG` for the domain
    knowledge graph (already ships labour + energy synonyms).
  * **cardinality** — oneToOne | memberSet | composite | timeSeries, classified
    against the wide column-groups detected in S0.
  * **soft type-penalty** — a measure that lands on a non-numeric column is never
    hidden; it is flagged ``typeMismatch=True`` with a reduced confidence.
  * **propose-only** — every binding is emitted ``status="proposed"``; nothing is
    auto-accepted (S2 confirms).

Deterministic and offline-first: with ``LLM_DISABLED=1`` the embedding stage is
skipped and stages 1–3 + human confirm still yield a complete bindingAST.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from report_builder.binding.schema import (
    BindingCandidate,
    BoundColumn,
    ColumnGroup,
    ColumnProfile,
    DatasetAST,
    EntityBinding,
)

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.40
_TYPE_PENALTY = 0.7
_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# entityType → column roles that are a clean (non-mismatch) fit.
_ROLE_FIT: dict[str, tuple[str, ...]] = {
    "measure": ("measure",),
    "dimension": ("dimension", "id", "metadata"),
    "filter": ("dimension", "id", "metadata"),
    "time": ("time",),
    "metadata": ("metadata", "dimension"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────


def _tokens(s: str) -> list[str]:
    return [t for t in _SPLIT_RE.split(str(s).lower()) if t]


def _normjoin(s: str) -> str:
    return "".join(_tokens(s))


def _singularize(word: str) -> str:
    w = str(word)
    if len(w) > 3 and w.lower().endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.lower().endswith("s") and not w.lower().endswith("ss"):
        return w[:-1]
    return w


def _entity_view(e: dict[str, Any]) -> dict[str, Any]:
    """Normalize a blueprint entity dict into the fields the resolver needs."""
    vd = e.get("valueDomain") or {}
    members = vd.get("members")
    if not isinstance(members, list):
        members = []
    return {
        "id": str(e.get("entityId") or e.get("id") or ""),
        "name": str(e.get("canonicalName") or e.get("entityName") or e.get("name") or ""),
        "type": str(e.get("entityType") or "dimension"),
        "aliases": [str(a) for a in (e.get("aliases") or [])],
        "members": [str(m) for m in members],
        "unit": e.get("unit"),
        "columnExpr": e.get("columnExpr"),
    }


def _is_total(col: str) -> bool:
    return "total" in {t.lower() for t in _tokens(col)}


def _member_label(col: str, group: ColumnGroup) -> str:
    """Derive a human label for a wide column inside a group (Proved_Reserves→Proved)."""
    stem_sing = _singularize(group.stem).lower()
    toks = [t for t in _tokens(col) if _singularize(t).lower() != stem_sing]
    return " ".join(t.capitalize() for t in toks) if toks else col


def _period_label(col: str, group: ColumnGroup) -> str:
    """Derive a period label for a wide column inside a periodGroup (WPR_2023_24→2023-24)."""
    stem = group.stem.lower()
    toks = [t for t in _tokens(col) if t != stem]
    return "-".join(toks) if toks else col


# ─────────────────────────────────────────────────────────────────────────────
# Candidate scoring
# ─────────────────────────────────────────────────────────────────────────────


def _score_candidates(
    view: dict[str, Any],
    dataset: DatasetAST,
    *,
    embedder: Any = None,
    top_k: int = 5,
) -> list[tuple[str, float, str]]:
    """Return ranked (column, confidence, method) candidates for an entity."""
    from deep_bi.column_synonym_kg import ColumnSynonymKG

    col_names = [p.name for p in dataset.columns]

    # Priority: if the entity declares a columnExpr that matches a dataset column exactly, use it
    column_expr = view.get("columnExpr") or ""
    if column_expr and column_expr in col_names:
        return [(column_expr, 0.99, "columnExpr")]

    own_phrases = [view["name"], *view["aliases"]]
    own_norms = {_normjoin(p) for p in own_phrases if p}

    kg = ColumnSynonymKG(col_names, bert_embedder=embedder)
    merged: dict[str, tuple[float, dict[str, float]]] = {}
    for phrase in own_phrases:
        if not phrase:
            continue
        for m in kg.resolve(phrase, top_k=top_k, min_score=0.0):
            prev = merged.get(m.column)
            if prev is None or m.score > prev[0]:
                merged[m.column] = (m.score, m.signals)

    ranked: list[tuple[str, float, str]] = []
    for col, (score, signals) in merged.items():
        method, conf = _method_and_confidence(col, score, signals, own_norms)
        ranked.append((col, conf, method))
    ranked.sort(key=lambda t: t[1], reverse=True)
    return ranked[:top_k]


def _method_and_confidence(
    col: str, kg_score: float, signals: dict[str, float], own_norms: set[str]
) -> tuple[str, float]:
    """Attribute a binding method and lift exact/alias confidence to sensible floors."""
    col_norm = _normjoin(col)
    # Exact: a phrase normalizes to exactly the column.
    if col_norm in own_norms:
        return "exact", max(kg_score, 0.98)
    # Alias: a phrase is a strong substring of the column (or vice versa).
    for pn in own_norms:
        if len(pn) >= 3 and (pn in col_norm or col_norm in pn):
            return "alias", max(kg_score, 0.88)
    # Embedding dominated.
    if signals.get("embedding", 0.0) >= 0.6 and signals["embedding"] >= max(
        signals.get("alias_exact", 0.0),
        signals.get("alias_contains", 0.0),
        signals.get("token_overlap", 0.0),
    ):
        return "embedding", kg_score
    return "synonym", kg_score


# ─────────────────────────────────────────────────────────────────────────────
# Cardinality classification
# ─────────────────────────────────────────────────────────────────────────────


def _matching_group(view: dict[str, Any], dataset: DatasetAST) -> ColumnGroup | None:
    """Find the column-group this entity is realized by, if any."""
    name_tok = set(_tokens(view["name"]))
    for a in view["aliases"]:
        name_tok |= set(_tokens(a))
    name_sing = {_singularize(t).lower() for t in name_tok}
    declared = {m.lower() for m in view["members"]}

    for g in dataset.columnGroups:
        stem_sing = _singularize(g.stem).lower()
        labels = {_member_label(c, g).lower() for c in g.members}
        if stem_sing in name_sing:
            return g
        if declared and (declared & labels):
            return g
    return None


def _classify_cardinality(
    view: dict[str, Any],
    best_col: str | None,
    dataset: DatasetAST,
) -> tuple[str, list[BoundColumn], str, list[str]]:
    """Return (cardinality, bound_columns, combine, notes)."""
    etype = view["type"]
    group = _matching_group(view, dataset)

    if group is not None:
        if group.kind == "periodGroup":
            cols = [BoundColumn(column=c, period=_period_label(c, group)) for c in group.members]
            return "timeSeries", cols, "none", [
                f"realized as {len(cols)} period columns via group '{group.stem}'"
            ]
        # measureGroup
        if etype in ("dimension", "filter"):
            cols = [
                BoundColumn(column=c, memberLabel=_member_label(c, group))
                for c in group.members
                if not _is_total(c)
            ]
            return "memberSet", cols, "none", [
                f"dimension realized as {len(cols)} wide member columns via group '{group.stem}'"
            ]
        if etype == "measure":
            total = next((c for c in group.members if _is_total(c)), None)
            if total is not None:
                return "composite", [BoundColumn(column=total)], "pick", [
                    f"explicit total column '{total}' used; member parts available for cross-check"
                ]
            parts = [BoundColumn(column=c) for c in group.members if not _is_total(c)]
            return "composite", parts, "sum", [
                f"no explicit total; summing {len(parts)} member parts of group '{group.stem}'"
            ]

    if best_col:
        return "oneToOne", [BoundColumn(column=best_col)], "none", []
    return "oneToOne", [], "none", []


def _type_mismatch(entity_type: str, profile: ColumnProfile | None) -> bool:
    if profile is None:
        return False
    fit = _ROLE_FIT.get(entity_type)
    if not fit:
        return False
    return profile.role not in fit


def _binding_evidence(
    view: dict[str, Any],
    ranked: list[tuple[str, float, str]],
    columns: list[BoundColumn],
    method: str,
    confidence: float,
    status: str,
) -> list[dict[str, Any]]:
    """Human/audit-readable evidence for why the resolver proposed this binding."""
    if status != "proposed" or not columns:
        return []
    primary = columns[0].column if columns else (ranked[0][0] if ranked else "")
    signal = {
        "exact": "exact_name",
        "alias": "alias",
        "glossary": "glossary",
        "embedding": "embedding",
        "synonym": "synonym",
        "manual": "manual",
    }.get(method, method or "synonym")
    evidence: list[dict[str, Any]] = [{
        "signal": signal,
        "score": round(float(confidence), 4),
        "detail": f"{view['name'] or view['id']} matched dataset column '{primary}'",
        "column": primary,
    }]
    for col, score, cand_method in ranked[:3]:
        if col == primary:
            continue
        evidence.append({
            "signal": f"candidate_{cand_method}",
            "score": round(float(score), 4),
            "detail": f"alternative candidate column '{col}'",
            "column": col,
        })
    if len(columns) > 1:
        evidence.append({
            "signal": "wide_group",
            "score": round(float(confidence), 4),
            "detail": f"{len(columns)} columns participate in the binding",
            "columns": [c.column for c in columns],
        })
    return evidence


def _binding_risks(type_mismatch: bool, view: dict[str, Any], best_col: str | None,
                   profile: ColumnProfile | None) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    if type_mismatch:
        risks.append({
            "code": "TYPE_MISMATCH",
            "severity": "warn",
            "message": (
                f"{view['type']} entity '{view['name'] or view['id']}' matched "
                f"{profile.role if profile else 'unknown'} column '{best_col or ''}'"
            ),
            "column": best_col or "",
        })
    return risks


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def resolve_entity(
    entity: dict[str, Any],
    dataset: DatasetAST,
    *,
    embedder: Any = None,
    min_confidence: float = _MIN_CONFIDENCE,
) -> EntityBinding:
    """Propose a binding for a single blueprint entity."""
    view = _entity_view(entity)
    ranked = _score_candidates(view, dataset, embedder=embedder)
    best_col, best_conf, best_method = (ranked[0] if ranked else (None, 0.0, "synonym"))

    # When columnExpr gave a direct match, force oneToOne — skip group detection
    if best_method == "columnExpr" and best_col:
        columns = [BoundColumn(column=best_col)]
        cardinality = "oneToOne"
        combine = "none"
        notes: list[str] = []
    else:
        cardinality, columns, combine, notes = _classify_cardinality(view, best_col, dataset)

    # Group bindings (memberSet/timeSeries/composite) carry their own confidence.
    if cardinality != "oneToOne":
        confidence = max(best_conf, 0.85)
        method = "alias"
        type_mismatch = False
        prof = None
    else:
        confidence = best_conf
        method = best_method
        prof = dataset.column(best_col) if best_col else None
        type_mismatch = _type_mismatch(view["type"], prof)
        if type_mismatch:
            confidence *= _TYPE_PENALTY
            notes = [*notes, f"type mismatch: {view['type']} entity landed on "
                     f"{prof.role if prof else 'unknown'} column '{best_col}'"]

    # Unresolved when nothing clears the bar and no group realized it.
    if not columns or (cardinality == "oneToOne" and confidence < min_confidence):
        status = "unresolved"
        if cardinality == "oneToOne":
            columns = []
    else:
        status = "proposed"

    alternatives = [
        BindingCandidate(column=c, confidence=round(conf, 4), method=meth)
        for c, conf, meth in ranked[1:4]
        if conf > 0.0
    ]

    return EntityBinding(
        entityId=view["id"],
        entityName=view["name"],
        entityType=view["type"],
        cardinality=cardinality,
        columns=columns,
        combine=combine,
        confidence=round(confidence, 4),
        method=method,
        status=status,
        alternatives=alternatives,
        typeMismatch=type_mismatch,
        notes=notes,
        evidence=_binding_evidence(view, ranked, columns, method, confidence, status),
        risks=_binding_risks(type_mismatch, view, best_col, prof),
    )


def resolve_entities(
    entities: list[dict[str, Any]],
    dataset: DatasetAST,
    *,
    embedder: Any = None,
    min_confidence: float = _MIN_CONFIDENCE,
) -> list[EntityBinding]:
    """Propose bindings for every blueprint entity (S1).

    When ``LLM_DISABLED`` is set the embedding stage is skipped automatically.
    """
    from report_builder.llm_router import llm_disabled

    if llm_disabled():
        embedder = None

    bindings = [
        resolve_entity(e, dataset, embedder=embedder, min_confidence=min_confidence)
        for e in entities
    ]
    resolved = sum(1 for b in bindings if b.status == "proposed")
    logger.info(
        "[resolver] %d/%d entities proposed (%d unresolved, %d type-mismatch)",
        resolved, len(bindings),
        sum(1 for b in bindings if b.status == "unresolved"),
        sum(1 for b in bindings if b.typeMismatch),
    )
    return bindings
