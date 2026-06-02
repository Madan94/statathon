"""Convert Stat Reports chapter AST (document/children) → report-builder blocks JSON."""
from __future__ import annotations

from typing import Any


def document_ast_to_report_blocks(payload: dict[str, Any]) -> dict[str, Any]:
    """Map `test_data/ast.json.txt` shape into validate_ast_payload-compatible dict."""
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
            "hints": {"chapter": doc.get("chapterNumber"), "source": doc.get("source")},
        }
    )

    for child in doc.get("children") or []:
        if not isinstance(child, dict):
            continue
        ctype = str(child.get("type") or "section")
        cid = str(child.get("id") or f"block_{len(blocks)}")

        if ctype == "section":
            blocks.append(
                {
                    "block_id": cid,
                    "kind": "narrative",
                    "title": str(child.get("title") or cid),
                    "section": "body",
                    "required": True,
                    "hints": {
                        "max_words": 350,
                        "tone": "official",
                        "template_section": cid,
                        "paragraphs": child.get("paragraphs"),
                        "frameworks": child.get("frameworks"),
                    },
                }
            )
            resource = child.get("resource")
            if isinstance(resource, dict):
                blocks.append(
                    {
                        "block_id": f"{cid}_metrics",
                        "kind": "metric",
                        "title": f"{resource.get('name', cid)} — Key figures",
                        "section": "body",
                        "required": False,
                        "hints": {
                            "source": "semantic_mapping",
                            "template_resource": resource,
                        },
                    }
                )
            figure = child.get("figure")
            if isinstance(figure, dict):
                chart_type = str(figure.get("type") or "bar").replace("_chart", "")
                blocks.append(
                    {
                        "block_id": str(figure.get("id") or f"{cid}_chart"),
                        "kind": "chart",
                        "title": f"{child.get('title', cid)} — Distribution",
                        "section": "body",
                        "required": False,
                        "hints": {
                            "chart_type": chart_type,
                            "source": "semantic_mapping",
                            "template_figure": figure,
                        },
                    }
                )
            if child.get("sources") or child.get("topStates"):
                blocks.append(
                    {
                        "block_id": f"{cid}_table_summary",
                        "kind": "table",
                        "title": f"{child.get('title', cid)} — Summary table",
                        "section": "body",
                        "required": False,
                        "hints": {
                            "source": "semantic_mapping",
                            "topStates": child.get("topStates"),
                            "sources": child.get("sources"),
                        },
                    }
                )
        elif ctype == "table":
            blocks.append(
                {
                    "block_id": cid,
                    "kind": "table",
                    "title": str(child.get("title") or cid),
                    "section": "appendix",
                    "required": True,
                    "hints": {
                        "source": "semantic_mapping",
                        "table_schema": child.get("schema"),
                    },
                }
            )

    blocks.append(
        {
            "block_id": "energy_findings",
            "kind": "narrative",
            "title": "Key Findings — Energy Reserves",
            "section": "findings",
            "required": True,
            "hints": {"max_words": 400, "verify_numbers": True, "tone": "official"},
        }
    )

    return {
        "name": title,
        "extraction_method": "energy_ast_json",
        "page_count": len(pages) if isinstance(pages, list) else 0,
        "source_document_id": doc.get("id"),
        "blocks": blocks,
    }
