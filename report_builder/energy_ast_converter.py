"""Convert Stat Reports chapter AST (document/children) → report-builder blocks JSON.

Each block carries rich `hints` so the pipeline renderer can produce
MoSPI-quality section-specific narratives, charts and tables without
any hardcoded values — all numbers are computed at render time from df.
"""
from __future__ import annotations

import re
from typing import Any


# Keyword → canonical Resource_Category mapping (case-insensitive)
_RESOURCE_KEYWORDS: dict[str, str] = {
    "coal": "Coal",
    "lignite": "Lignite",
    "crude oil": "Crude Oil",
    "crude": "Crude Oil",
    "natural gas": "Natural Gas",
    "gas": "Natural Gas",
    "renewable": "Renewable Energy",
    "solar": "Renewable Energy",
    "wind": "Renewable Energy",
    "hydro": "Renewable Energy",
}


def _infer_resource(section_id: str, title: str) -> str | None:
    """Infer resource category from section id / title keywords."""
    text = (section_id + " " + title).lower()
    for kw, cat in _RESOURCE_KEYWORDS.items():
        if kw in text:
            return cat
    return None


def document_ast_to_report_blocks(payload: dict[str, Any]) -> dict[str, Any]:
    """Map `test_data/ast.json.txt` shape into validate_ast_payload-compatible dict.

    Compared to the original converter, every block now carries a
    ``resource_category`` hint (where detectable) so that:
    - Tables are filtered to that resource
    - Charts show % distribution within that resource
    - Narratives receive resource-specific analytics context
    """
    doc = payload.get("document") if isinstance(payload.get("document"), dict) else payload
    title = str(doc.get("title") or "Energy Reserves Report")
    pages = doc.get("pages") or []
    blocks: list[dict[str, Any]] = []

    blocks.append(
        {
            "block_id": "chapter_heading",
            "kind": "heading",
            "title": title,
            "section": "cover",
            "required": True,
            "hints": {
                "chapter": doc.get("chapterNumber"),
                "source": doc.get("source"),
            },
        }
    )

    for child in doc.get("children") or []:
        if not isinstance(child, dict):
            continue
        ctype = str(child.get("type") or "section")
        cid = str(child.get("id") or f"block_{len(blocks)}")
        ctitle = str(child.get("title") or cid)
        resource_cat = _infer_resource(cid, ctitle)

        if ctype == "section":
            # ── Narrative block ──────────────────────────────────────────
            blocks.append(
                {
                    "block_id": cid,
                    "kind": "narrative",
                    "title": ctitle,
                    "section": "body",
                    "required": True,
                    "hints": {
                        "max_words": 350,
                        "tone": "official",
                        "template_section": cid,
                        "resource_category": resource_cat,
                        "paragraphs": child.get("paragraphs"),
                        "frameworks": child.get("frameworks"),
                        # These keys signal the renderer to compute MoSPI-style stats
                        "compute_pct_distribution": True,
                        "compute_top_states": True,
                        "top_n_states": 3,
                    },
                }
            )

            # ── Metric block ─────────────────────────────────────────────
            resource = child.get("resource")
            if isinstance(resource, dict):
                blocks.append(
                    {
                        "block_id": f"{cid}_metrics",
                        "kind": "metric",
                        "title": f"{resource.get('name', ctitle)} — Key figures",
                        "section": "body",
                        "required": False,
                        "hints": {
                            "source": "energy_dataset",
                            "resource_category": resource_cat,
                            "template_resource": resource,
                            "metrics": [
                                "total_reserves", "proved_reserves",
                                "indicated_reserves", "inferred_reserves",
                                "state_count", "proved_pct", "indicated_pct", "inferred_pct",
                            ],
                        },
                    }
                )

            # ── Chart block ──────────────────────────────────────────────
            figure = child.get("figure")
            if isinstance(figure, dict):
                chart_type = str(figure.get("type") or "pie").replace("_chart", "")
                # Coal/Lignite → pie (proved/indicated/inferred %)
                # States → bar
                if resource_cat and "state" not in cid.lower() and "geo" not in cid.lower():
                    chart_type = "pie"
                    chart_group = "reserve_type"   # pie over Proved/Indicated/Inferred %
                else:
                    chart_type = "bar"
                    chart_group = "state"
                blocks.append(
                    {
                        "block_id": str(figure.get("id") or f"{cid}_chart"),
                        "kind": "chart",
                        "title": f"{ctitle} — Distribution",
                        "section": "body",
                        "required": False,
                        "hints": {
                            "chart_type": chart_type,
                            "source": "energy_dataset",
                            "resource_category": resource_cat,
                            "chart_group": chart_group,
                            "show_pct": True,
                            "template_figure": figure,
                        },
                    }
                )

            # ── Summary table block ──────────────────────────────────────
            if child.get("sources") or child.get("topStates"):
                blocks.append(
                    {
                        "block_id": f"{cid}_table_summary",
                        "kind": "table",
                        "title": f"{ctitle} — Summary table",
                        "section": "body",
                        "required": False,
                        "hints": {
                            "source": "energy_dataset",
                            "resource_category": resource_cat,
                            "group_by": "Resource_Category" if not resource_cat else "State",
                            "show_pct": True,
                            "topStates": child.get("topStates"),
                            "sources": child.get("sources"),
                        },
                    }
                )

        elif ctype == "table":
            # Appendix statewise tables — detect resource from title
            table_title = str(child.get("title") or cid)
            table_resource = _infer_resource(cid, table_title)
            blocks.append(
                {
                    "block_id": cid,
                    "kind": "table",
                    "title": table_title,
                    "section": "appendix",
                    "required": True,
                    "hints": {
                        "source": "energy_dataset",
                        "resource_category": table_resource,
                        "group_by": "State",
                        "show_pct": True,
                        "table_schema": child.get("schema"),
                    },
                }
            )

    # ── Key Findings narrative ───────────────────────────────────────────
    blocks.append(
        {
            "block_id": "energy_findings",
            "kind": "narrative",
            "title": "Key Findings — Energy Reserves",
            "section": "findings",
            "required": True,
            "hints": {
                "max_words": 400,
                "verify_numbers": True,
                "tone": "official",
                "compute_pct_distribution": True,
                "compute_top_states": True,
                "top_n_states": 5,
            },
        }
    )

    return {
        "name": title,
        "extraction_method": "energy_ast_json",
        "page_count": len(pages) if isinstance(pages, list) else 0,
        "source_document_id": doc.get("id"),
        "blocks": blocks,
    }
