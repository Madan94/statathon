"""S5a-bridge — render-ready synthesis for *documentMap* template archetypes.

Some gold templates (e.g. ``tpl_energy_enterprise_v2``) ship a ``documentMap``
tree (topic → chapter → section → question → typed slots) instead of the
``semanticAST.sections`` + ``tableAST``/``chartAST`` slot archetype that
:func:`report_builder.generation.filler.fill_visuals` consumes. For those
templates the monolithic generate pass fills nothing and the standalone report
renders an empty shell — even though S4 analytics are fully computed.

This module bridges that gap **without touching the existing pipeline**: it reads
the ``documentMap`` plus the already-computed ``analyticsAST`` (linked by the
shared ``questionId``) and emits filled ``tableAST`` / ``chartAST`` / ``figureAST``
artifacts, narrative ``contentAST`` blocks, and a ``semanticAST.sections`` tree
whose children reference those artifacts by id. Output matches the §0 render
contracts exactly, so :func:`render_html` renders it unchanged.

Fully deterministic and offline. Used only when a template is documentMap-shaped.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Analytics indexing (questionId → roll-up)
# ─────────────────────────────────────────────────────────────────────────────


def _index_analytics(analytics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    # A multi-measure question fans out into several rankings/aggregations sharing
    # the same questionId. The FIRST one is the question's PRIMARY measure (the
    # adapter emits it first); keep that so the narrative/table cite the headline
    # measure, not a secondary table column. (A dict comprehension keeps the LAST,
    # which made "rank by establishments" narrate "Persons Working".)
    rankings: dict[str, dict[str, Any]] = {}
    for r in analytics.get("rankings", []):
        qid = r.get("questionId")
        if qid and qid not in rankings:
            rankings[qid] = r
    aggregations: dict[str, dict[str, Any]] = {}
    for a in analytics.get("aggregations", []):
        qid = a.get("questionId")
        if qid and qid not in aggregations:
            aggregations[qid] = a
    metrics: dict[str, list[dict[str, Any]]] = {}
    for m in analytics.get("metrics", []):
        qid = m.get("questionId")
        if qid:
            metrics.setdefault(qid, []).append(m)
    trends: dict[str, dict[str, Any]] = {}
    for t in analytics.get("trends", []):
        qid = t.get("questionId")
        if qid and qid not in trends:
            trends[qid] = t
    return {"rankings": rankings, "aggregations": aggregations, "metrics": metrics, "trends": trends}


def _index_evidence(evidence: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ev in evidence.get("evidence", []):
        qid = ev.get("questionId")
        if qid and qid not in out:
            out[qid] = ev.get("evidenceId")
    return out


def _fmt(value: Any) -> str:
    """Human-readable number with Indian-style grouping; pass through non-numbers."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, (int, float)):
        n = float(value)
        if n.is_integer():
            return f"{int(n):,}"
        return f"{n:,.2f}"
    return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# Artifact builders (match §0 render contracts)
# ─────────────────────────────────────────────────────────────────────────────


def _dims_of(rows: list[dict[str, Any]]) -> list[str]:
    for r in rows:
        key = r.get("key") or {}
        if isinstance(key, dict) and key:
            return list(key.keys())
    return []


def _table_from_ranking(table_id: str, ranking: dict[str, Any], q_title: str = "") -> dict[str, Any]:
    items = ranking.get("items") or []
    dims = _dims_of(items)
    measure = ranking.get("measure") or "Value"
    columns = [{"columnId": "rank", "header": "Rank", "role": "dimension", "align": "center"}]
    for d in dims:
        columns.append({"columnId": d, "header": d, "role": "dimension"})
    columns.append({"columnId": "value", "header": measure, "role": "measure"})
    rows: list[dict[str, Any]] = []
    for it in items:
        key = it.get("key") or {}
        row: dict[str, Any] = {"rank": it.get("rank")}
        for d in dims:
            row[d] = key.get(d)
        row["value"] = it.get("value")
        row["rowIds"] = list(it.get("rowIds") or [])
        rows.append(row)
    # Use question title if provided, else synthesize from measure + dimensions
    title = q_title.strip() if q_title else f"{measure} by {', '.join(dims) or 'group'}"
    return {"tableId": table_id, "title": title, "columns": columns, "rows": rows}


def _table_from_agg(table_id: str, agg: dict[str, Any], q_title: str = "") -> dict[str, Any]:
    agg_rows = agg.get("rows") or []
    dims = _dims_of(agg_rows)
    measure = agg.get("measure") or "Value"
    columns = [{"columnId": d, "header": d, "role": "dimension"} for d in dims]
    columns.append({"columnId": "value", "header": measure, "role": "measure"})
    rows: list[dict[str, Any]] = []
    for r in agg_rows:
        key = r.get("key") or {}
        row: dict[str, Any] = {d: key.get(d) for d in dims}
        row["value"] = r.get("value")
        row["rowIds"] = list(r.get("rowIds") or [])
        rows.append(row)
    # Use question title if provided, else synthesize from measure + dimensions
    title = q_title.strip() if q_title else f"{measure} by {', '.join(dims) or 'group'}"
    return {"tableId": table_id, "title": title, "columns": columns, "rows": rows}


# Chart types the deterministic SVG kit renders for a single-series roll-up.
_SINGLE_SERIES_OK = frozenset({"bar", "simple_bar", "pie", "donut", "line"})


def _chart_from(chart_id: str, rollup: dict[str, Any], *, kind: str,
                chart_type: str = "bar", title: str = "") -> dict[str, Any]:
    """Build a chartAST from a ranking (items) or aggregation (rows).

    ``chart_type`` is the template's declared type (from the slot graph). Multi-
    series types (grouped_bar/stacked_bar/stacked_100) gracefully fall back to a
    single-series bar here since the bridge derives one measure series per slot;
    pie/donut/line render natively. ``title`` is the template's declared (unique)
    chart title; when absent a deterministic title is synthesized.
    """
    measure = rollup.get("measure") or "Value"
    src = rollup.get("items") if kind == "ranking" else rollup.get("rows")
    src = src or []
    dims = _dims_of(src)
    dim0 = dims[0] if dims else None
    points: list[dict[str, Any]] = []
    for entry in src[:12]:
        key = entry.get("key") or {}
        x = key.get(dim0) if dim0 else None
        points.append({"x": x, "y": entry.get("value"), "rowIds": list(entry.get("rowIds") or [])})
    ctype = (chart_type or "bar").strip().lower()
    if ctype not in _SINGLE_SERIES_OK:
        ctype = "bar"  # grouped/stacked need 2 dims → degrade to bar
    chart_title = title.strip() if title else (f"{measure}" + (f" by {dim0}" if dim0 else ""))
    return {
        "chartId": chart_id,
        "chartType": ctype,
        "title": chart_title,
        "yAxis": {"unit": None, "label": measure},
        "series": [{"label": measure, "points": points}] if points else [],
    }


def _looks_numeric(text: str) -> bool:
    try:
        float(str(text).replace(",", ""))
        return True
    except (TypeError, ValueError):
        return False


def _key_label(key: dict[str, Any]) -> str:
    """Readable group label using only non-numeric dimension members.

    Numeric members (e.g. a year like ``2025``) are dropped so the prose never
    states a number that isn't an analytics value — which the verifier would flag.
    """
    bits = [str(v).strip() for v in (key or {}).values()
            if str(v).strip() and not _looks_numeric(v)]
    return ", ".join(bits)


def _narrative_for(q_title: str, rollup_kind: str, rollup: dict[str, Any] | None,
                   metrics: list[dict[str, Any]] | None) -> str:
    """Deterministic, data-backed prose for a question's narrative slot.

    Produces a richer, multi-sentence analytical paragraph (lead → leaders →
    spread/concentration → tail → metric) while only citing numbers that are
    genuine analytics values (ranking item values, aggregation row values, metric
    values) so every figure verifies — no derived sums the verifier cannot
    reconcile. Ratios *between* two cited values are safe because both endpoints
    are themselves verifiable analytics values.
    """
    head = (q_title or "").strip().rstrip(".")
    parts: list[str] = []
    if head:
        parts.append(head + ".")

    if rollup_kind == "ranking" and rollup and rollup.get("items"):
        items = rollup["items"]
        measure = rollup.get("measure") or "the measure"
        dims = _dims_of(items)
        d0 = dims[0] if dims else None

        def label(it: dict[str, Any]) -> str:
            k = it.get("key") or {}
            return (str(k.get(d0)) if d0 else "") or "the leading unit"

        top = items[0]
        top_val = top.get("value")
        # Lead sentence — the front-runner.
        sent = f"{label(top)} leads on {measure} at {_fmt(top_val)}"
        extras = [f"{label(it)} ({_fmt(it.get('value'))})" for it in items[1:3]]
        if extras:
            sent += ", followed by " + " and ".join(extras)
        parts.append(sent + ".")

        # Spread / concentration sentence — only ratios between two cited values.
        if len(items) >= 4:
            low = items[-1]
            low_val = low.get("value")
            parts.append(
                f"At the other end, {label(low)} records the lowest value at {_fmt(low_val)}."
            )
            try:
                if low_val and float(low_val) != 0:
                    ratio = float(top_val) / float(low_val)
                    if ratio >= 1.5:
                        parts.append(
                            f"The leader's {measure} is about {ratio:.1f} times that of the "
                            f"lowest-ranked unit, indicating a pronounced spread across the "
                            f"distribution."
                        )
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            # Top-3 prominence relative to the leader (both endpoints are cited values).
            try:
                third_val = items[2].get("value")
                if third_val and float(top_val) and float(third_val) / float(top_val) >= 0.75:
                    parts.append(
                        "The top three units cluster closely, sharing the upper band of the "
                        "distribution."
                    )
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    elif rollup_kind == "aggregation" and rollup and rollup.get("rows"):
        rows = rollup["rows"]
        measure = rollup.get("measure") or "the measure"
        ordered = sorted(rows, key=lambda r: (r.get("value") or 0), reverse=True)
        top = ordered[0]
        top_val = top.get("value")
        sent = (f"The highest {measure} is recorded by "
                f"{_key_label(top.get('key') or {}) or 'the leading group'} at {_fmt(top_val)}")
        if len(ordered) > 1:
            bot = ordered[-1]
            bot_val = bot.get("value")
            sent += (f"; the lowest is {_key_label(bot.get('key') or {}) or 'the trailing group'} "
                     f"at {_fmt(bot_val)}")
        parts.append(sent + ".")
        if len(ordered) >= 3:
            mid = ordered[len(ordered) // 2]
            parts.append(
                f"The median group, {_key_label(mid.get('key') or {}) or 'the central group'}, "
                f"sits at {_fmt(mid.get('value'))}, anchoring the middle of the range."
            )

    if metrics:
        m = metrics[0]
        m_val = m.get("value")
        # Composition / refused-formula questions can carry a metric with no value;
        # never narrate "stands at None" — cite it only when there is a real number.
        if m_val is not None:
            lbl = (m.get("label") or "").strip().rstrip(".")
            if lbl:
                parts.append(f"The corresponding all-India figure for {lbl} stands at {_fmt(m_val)}.")
            else:
                parts.append(f"The corresponding all-India {(rollup or {}).get('measure') or 'value'} "
                             f"stands at {_fmt(m_val)}.")

    if len(parts) <= 1:
        parts.append("The accompanying chart and table present the detailed breakdown for "
                     "this indicator across the reported units.")
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# documentMap walk
# ─────────────────────────────────────────────────────────────────────────────


def _iter_questions(document_map: list[dict[str, Any]]):
    """Yield ``(topic, chapter, section, question)`` nodes in document order.

    Tolerates missing intermediate levels (questions may hang off a chapter or a
    topic directly).
    """
    for topic in document_map or []:
        if (topic.get("nodeType") or "") not in ("topic", ""):
            continue
        chapters = topic.get("children") or []
        if not chapters:
            for q in []:
                yield topic, None, None, q
        for child in chapters:
            ntype = child.get("nodeType")
            if ntype == "question":
                yield topic, None, None, child
                continue
            chapter = child
            for sub in chapter.get("children") or []:
                if sub.get("nodeType") == "question":
                    yield topic, chapter, None, sub
                    continue
                section = sub
                for q in section.get("children") or []:
                    if q.get("nodeType") == "question":
                        yield topic, chapter, section, q


def _chart_meta_index(slot_graph: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, str]]:
    """Map slotId / componentRef → (declared chartType, declared chartTitle).

    The template's ``semantic_slot_graph.json`` declares a distinct chartType and
    a unique chartTitle per chart slot. Without the type every chart degrades to a
    bar; without the title the bridge synthesizes a measure-based title that can
    collide across slots. Honoring both removes overlap and adds variety.
    """
    types: dict[str, str] = {}
    titles: dict[str, str] = {}
    if not isinstance(slot_graph, dict):
        return types, titles
    slots = slot_graph.get("slots") or slot_graph.get("semanticSlots") or []
    for s in slots:
        if not isinstance(s, dict) or s.get("slotType") != "chart":
            continue
        oc = s.get("outputContract") or {}
        ctype = oc.get("chartType") or (s.get("chartSpec") or {}).get("chartType")
        title = s.get("chartTitle") or oc.get("title") or (s.get("chartSpec") or {}).get("title")
        for key in (s.get("slotId"), s.get("componentRef")):
            if not key:
                continue
            if ctype:
                types[key] = ctype
            if title:
                titles[key] = title
    return types, titles


def bridge_document_map_report(
    document_map: list[dict[str, Any]],
    analytics: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    slot_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Synthesize render-ready artifacts for a documentMap-archetype template.

    Returns a dict with ``semanticAST`` (sections tree), ``tableAST``,
    ``chartAST``, ``figureAST`` and ``blocks`` (contentAST paragraphs), all keyed
    to the computed analytics so :func:`render_html` produces a full report.
    ``slot_graph`` (optional) supplies the declared per-slot chart types.
    """
    evidence = evidence or {}
    aidx = _index_analytics(analytics)
    eidx = _index_evidence(evidence)
    chart_types, chart_titles = _chart_meta_index(slot_graph)

    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []

    # Group questions by their owning section node (or chapter/topic fallback) so
    # each rendered <section> carries a meaningful heading and its question slots.
    grouped: list[tuple[str, str, list[tuple[dict, dict, dict, dict]]]] = []
    index_by_key: dict[str, int] = {}
    for topic, chapter, section, q in _iter_questions(document_map):
        owner = section or chapter or topic
        key = owner.get("nodeId") or owner.get("title") or id(owner)
        crumb = " · ".join(
            t for t in [
                (chapter or {}).get("title") if chapter else None,
                (section or {}).get("title") if section else None,
            ] if t
        ) or owner.get("title") or "Section"
        if key not in index_by_key:
            index_by_key[key] = len(grouped)
            grouped.append((str(key), crumb, []))
        grouped[index_by_key[key]][2].append((topic, chapter, section, q))

    order = 0
    last_topic_id: str | None = None
    for key, crumb, qnodes in grouped:
        topic = qnodes[0][0]
        topic_id = topic.get("nodeId") or topic.get("title")
        # Topic divider section (heading only) when the topic changes.
        if topic_id != last_topic_id:
            order += 1
            sections.append({
                "sectionId": f"sec_topic_{topic_id}",
                "title": topic.get("title") or "Topic",
                "order": order,
                "children": [],
                "level": 1,
            })
            last_topic_id = topic_id

        children: list[str] = []
        for _t, _c, _s, q in qnodes:
            qid = q.get("nodeId")
            q_title = q.get("title") or qid
            ranking = aidx["rankings"].get(qid)
            agg = aidx["aggregations"].get(qid)
            metrics = aidx["metrics"].get(qid) or []
            roll_kind = "ranking" if ranking else ("aggregation" if agg else "")
            rollup = ranking or agg
            an_ref = (ranking or {}).get("rankId") or (agg or {}).get("aggId") \
                or (metrics[0].get("metricId") if metrics else None)
            ev_ref = eidx.get(qid)
            prov = {"questionId": qid, "analyticsRef": an_ref, "evidenceRef": ev_ref}

            slots = q.get("slots") or []
            # Default slot set when the template question carries none.
            if not slots:
                slots = [{"slotId": f"{qid}_narrative", "slotType": "narrative"}]
                if rollup:
                    slots.append({"slotId": f"{qid}_table", "slotType": "table"})

            for slot in slots:
                stype = slot.get("slotType")
                sid = slot.get("slotId") or f"{qid}_{stype}"
                if stype == "narrative":
                    blocks.append({
                        "blockId": sid,
                        "kind": "paragraph",
                        "content": _narrative_for(q_title, roll_kind, rollup, metrics),
                        "provenance": prov,
                        "slot": {"status": "filled"},
                    })
                    children.append(sid)
                elif stype == "table" and rollup:
                    tbl = _table_from_ranking(sid, ranking, q_title) if ranking else _table_from_agg(sid, agg, q_title)
                    tbl["provenance"] = prov
                    tbl["slot"] = {"status": "filled"}
                    tables.append(tbl)
                    children.append(sid)
                elif stype == "chart" and rollup:
                    cid = f"{sid}_chart"
                    declared = (chart_types.get(sid)
                                or chart_types.get(slot.get("componentRef"))
                                or "bar")
                    declared_title = (chart_titles.get(sid)
                                      or chart_titles.get(slot.get("componentRef"))
                                      or "")
                    ch = _chart_from(cid, rollup, kind=roll_kind, chart_type=declared, title=declared_title)
                    ch["provenance"] = prov
                    ch["slot"] = {"status": "filled" if ch.get("series") else "empty"}
                    charts.append(ch)
                    figures.append({
                        "figureId": sid,
                        "chartRef": cid,
                        "caption": ch.get("title") or q_title,
                        "provenance": prov,
                        "slot": {"status": ch["slot"]["status"]},
                    })
                    children.append(sid)

        order += 1
        sections.append({
            "sectionId": f"sec_{key}",
            "title": crumb,
            "order": order,
            "children": children,
            "level": 2,
        })

    logger.info(
        "[S5a-bridge] documentMap → %d sections, %d tables, %d charts, %d figures, %d blocks",
        len(sections), len(tables), len(charts), len(figures), len(blocks),
    )
    return {
        "semanticAST": {"sections": sections},
        "tableAST": {"tables": tables},
        "chartAST": {"charts": charts},
        "figureAST": {"figures": figures},
        "blocks": blocks,
    }
