"""R1.4 — document chrome for the render layer.

Cover page, table of contents, running header/footer (``@page`` boxes), page
numbers, figure/table numbering, and a provenance appendix. All of these are
**opt-in** so the default ``render_html`` output (and the gold snapshot) is
unchanged; callers enable them per export.

Reads only §0 contracts (``semanticAST``, ``figureAST``, ``tableAST``,
``metadata``/``provenanceAST``) and degrades gracefully on missing fields.
"""
from __future__ import annotations

from typing import Any

from .numbers import esc
from .theme import Theme, get_theme


# ─────────────────────────────────────────────────────────────────────────────
# Cover page
# ─────────────────────────────────────────────────────────────────────────────


def build_cover(report: dict[str, Any], theme: Theme | str | None = None) -> str:
    """Title page: ministry line, title, period, report id, status, logo slot."""
    th = get_theme(theme)
    meta = report.get("metadata") or {}
    sections = (report.get("semanticAST") or {}).get("sections", [])
    title = meta.get("title") or _first_section_title(sections) or "Statistical Report"
    subtitle = meta.get("subtitle") or ""
    period = (meta.get("period") or {}).get("current") or ""
    report_id = meta.get("reportId") or ""
    status = meta.get("status") or ""
    ministry = meta.get("ministry") or "Ministry of Statistics and Programme Implementation"
    org = meta.get("organisation") or "Government of India"
    logo = meta.get("logoRef")

    logo_html = (
        f'<img class="cover-logo" src="{esc(logo)}" alt="logo"/>' if logo
        else '<div class="cover-logo cover-logo-placeholder" aria-hidden="true"></div>'
    )
    bits = []
    if period:
        bits.append(f'<div class="cover-period">Reference period: {esc(period)}</div>')
    if report_id:
        bits.append(f'<div class="cover-id">Report ID: {esc(report_id)}</div>')
    if status:
        bits.append(f'<div class="cover-status">Status: {esc(status)}</div>')

    sub_html = f'<div class="cover-subtitle">{esc(subtitle)}</div>' if subtitle else ""
    return (
        '<section class="cover-page">'
        f"{logo_html}"
        f'<div class="cover-ministry">{esc(ministry)}</div>'
        f'<div class="cover-org">{esc(org)}</div>'
        f'<h1 class="cover-title">{esc(title)}</h1>'
        f"{sub_html}"
        f'<div class="cover-meta">{"".join(bits)}</div>'
        "</section>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Table of contents
# ─────────────────────────────────────────────────────────────────────────────


def build_toc(sections: list[dict[str, Any]]) -> str:
    """Numbered TOC. Page numbers are filled by the print engine via CSS
    ``target-counter`` (``a::after { content: target-counter(...) }``)."""
    if not sections:
        return ""
    items = []
    for i, sec in enumerate(sorted(sections, key=lambda s: s.get("order", 0)), start=1):
        title = sec.get("title")
        if not title:
            continue
        sec_id = sec.get("sectionId") or f"sec-{i}"
        items.append(
            f'<li class="toc-item"><a href="#{esc(sec_id)}">'
            f'<span class="toc-num">{i}.</span> {esc(title)}</a></li>'
        )
    if not items:
        return ""
    return (
        '<nav class="toc"><h2 class="toc-heading">Contents</h2>'
        f'<ol class="toc-list">{"".join(items)}</ol></nav>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# @page running header / footer + page numbers
# ─────────────────────────────────────────────────────────────────────────────


def running_header_footer_css(report: dict[str, Any], theme: Theme | str | None = None) -> str:
    """`@page` CSS: title (top), page N (bottom-right), ministry/date lines."""
    th = get_theme(theme)
    meta = report.get("metadata") or {}
    title = meta.get("title") or "Statistical Report"
    ministry = meta.get("ministry") or "MoSPI"
    m = th.margins
    return (
        "@page {{ size: {size}; margin: {mt} {mr} {mb} {ml}; "
        '@top-left {{ content: "{title}"; font-size: 9px; color: {muted}; }} '
        '@top-right {{ content: "{ministry}"; font-size: 9px; color: {muted}; }} '
        '@bottom-right {{ content: "Page " counter(page) " of " counter(pages); '
        "font-size: 9px; color: {muted}; }} "
        '@bottom-left {{ content: "{title}"; font-size: 9px; color: {muted}; }} }} '
        ".cover-page {{ page: cover; }} "
        "@page cover {{ @top-left {{ content: none; }} @top-right {{ content: none; }} "
        "@bottom-left {{ content: none; }} @bottom-right {{ content: none; }} }}"
    ).format(
        size=th.page_size,
        mt=m[0], mr=m[1], mb=m[2], ml=m[3],
        title=esc(title), ministry=esc(ministry), muted=th.muted,
    )


def document_css() -> str:
    """Static cover/TOC styling (theme colours pulled from CSS vars already set)."""
    return (
        ".cover-page { text-align: center; padding: 80px 40px; "
        "page-break-after: always; }"
        ".cover-logo { width: 96px; height: 96px; margin: 0 auto 24px; display: block; }"
        ".cover-logo-placeholder { border: 2px dashed var(--line); border-radius: 8px; }"
        ".cover-ministry { font-size: 15px; font-weight: 600; color: var(--accent); }"
        ".cover-org { font-size: 13px; color: var(--muted); margin-bottom: 48px; }"
        ".cover-title { font-size: 30px; margin: 24px 0 8px; color: var(--ink); }"
        ".cover-subtitle { font-size: 16px; color: var(--muted); margin-bottom: 32px; }"
        ".cover-meta { font-size: 13px; color: var(--muted); margin-top: 40px; "
        "line-height: 1.9; }"
        ".toc { page-break-after: always; margin-bottom: 28px; }"
        ".toc-heading { font-size: 18px; border-left: 4px solid var(--accent); "
        "padding-left: 10px; }"
        ".toc-list { list-style: none; padding: 0; }"
        ".toc-item { margin: 6px 0; font-size: 14px; }"
        ".toc-item a { text-decoration: none; color: var(--ink); }"
        ".toc-num { color: var(--accent); font-weight: 600; margin-right: 8px; }"
        ".toc-item a::after { content: leader('.') target-counter(attr(href), page); "
        "color: var(--muted); }"
        ".provenance-appendix { page-break-before: always; }"
        ".provenance-appendix h2 { font-size: 18px; border-left: 4px solid var(--accent); "
        "padding-left: 10px; }"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Figure / table numbering (opt-in mutation)
# ─────────────────────────────────────────────────────────────────────────────


def number_figures_tables(report: dict[str, Any]) -> dict[str, Any]:
    """Assign ``Figure {sec}.{seq}`` / ``Table {sec}.{seq}`` prefixes.

    Mutates the passed report **in place** and returns it. Walks sections in
    order so numbers follow document flow. Idempotent-ish: skips captions/titles
    that already start with the prefix.
    """
    sections = (report.get("semanticAST") or {}).get("sections", [])
    figures = {f.get("figureId"): f for f in (report.get("figureAST") or {}).get("figures", [])}
    tables = {t.get("tableId"): t for t in (report.get("tableAST") or {}).get("tables", [])}

    for sec_idx, sec in enumerate(sorted(sections, key=lambda s: s.get("order", 0)), start=1):
        fig_seq = 0
        tbl_seq = 0
        for child_id in sec.get("children") or []:
            if child_id in figures:
                fig_seq += 1
                fig = figures[child_id]
                label = f"Figure {sec_idx}.{fig_seq}"
                cap = fig.get("caption") or ""
                if not cap.startswith("Figure "):
                    fig["caption"] = f"{label}: {cap}".rstrip(": ").strip() if cap else label
                fig["figureNumber"] = label
            elif child_id in tables:
                tbl_seq += 1
                tbl = tables[child_id]
                label = f"Table {sec_idx}.{tbl_seq}"
                ttl = tbl.get("title") or ""
                if not ttl.startswith("Table "):
                    tbl["title"] = f"{label}: {ttl}".rstrip(": ").strip() if ttl else label
                tbl["tableNumber"] = label
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Provenance appendix
# ─────────────────────────────────────────────────────────────────────────────


def build_provenance_appendix(report: dict[str, Any]) -> str:
    """Evidence table: questionId / componentId / rowIds / analyticsRef.

    Pulls from ``provenanceAST.evidence`` when present, else scans block
    provenance. Returns '' when there is nothing to show.
    """
    rows: list[tuple[str, str, str, str, str]] = []
    prov = report.get("provenanceAST") or {}
    evidence = prov.get("evidence") or []
    for ev in evidence:
        rows.append((
            str(ev.get("questionId") or ""),
            str(ev.get("planId") or ""),
            str(ev.get("componentId") or ev.get("evidenceId") or ""),
            str(ev.get("analyticsRef") or ev.get("computation") or ""),
            ", ".join(ev.get("rowIds") or []),
        ))
    if not rows:
        audit_prov = (report.get("auditAST") or {}).get("provenance") or {}
        for entry in audit_prov.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            rows.append((
                str(entry.get("questionId") or ""),
                str(entry.get("planId") or ""),
                str(entry.get("componentRef") or ""),
                str(entry.get("analyticsRef") or ""),
                ", ".join(entry.get("rowIds") or []),
            ))
    if not rows:
        for b in (report.get("contentAST") or {}).get("blocks", []):
            p = b.get("provenance") or {}
            if p:
                rows.append((
                    str(p.get("questionId") or ""),
                    str(p.get("planId") or ""),
                    str(p.get("componentId") or ""),
                    str(p.get("analyticsRef") or ""),
                    ", ".join(p.get("evidenceRef") or []) if isinstance(p.get("evidenceRef"), list)
                    else str(p.get("evidenceRef") or ""),
                ))
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""

    body = []
    for q, plan, c, a, ids in rows:
        body.append(
            f"<tr><td>{esc(q)}</td><td>{esc(plan)}</td><td>{esc(c)}</td>"
            f"<td>{esc(a)}</td><td>{esc(ids)}</td></tr>"
        )
    return (
        '<section class="provenance-appendix"><h2>Appendix: Provenance</h2>'
        '<table class="data-table"><thead><tr>'
        "<th>Question</th><th>Plan</th><th>Component</th><th>Analytics</th><th>Row IDs</th>"
        f'</tr></thead><tbody>{"".join(body)}</tbody></table></section>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _first_section_title(sections: list[dict[str, Any]]) -> str:
    for s in sorted(sections, key=lambda s: s.get("order", 0)):
        if s.get("title"):
            return s["title"]
    return ""
