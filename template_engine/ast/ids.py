"""Deterministic ID helpers for enterprise AST nodes."""
from __future__ import annotations


def page_id(index: int) -> str:
    return f"page_{index + 1:03d}"


def paragraph_id(index: int) -> str:
    return f"p_{index + 1:03d}"


def table_id(index: int) -> str:
    return f"table_{index + 1:03d}"


def figure_id(index: int) -> str:
    return f"fig_{index + 1:03d}"


def chart_id(index: int) -> str:
    return f"chart_{index + 1:03d}"


def section_id(index: int) -> str:
    return f"section_{index + 1:03d}"


def style_id(index: int) -> str:
    return f"style_{index + 1:03d}"


def geometry_node_id(prefix: str, index: int) -> str:
    return f"geo_{prefix}_{index + 1:03d}"


def asset_id(index: int) -> str:
    return f"asset_{index + 1:03d}"


def entity_id(index: int) -> str:
    return f"ent_{index + 1:03d}"


def relationship_id(index: int) -> str:
    return f"rel_{index + 1:03d}"


def concept_id(index: int) -> str:
    return f"concept_{index + 1:03d}"


def fact_id(index: int) -> str:
    return f"fact_{index + 1:03d}"


def citation_id(index: int) -> str:
    return f"cite_{index + 1:03d}"


def chunk_id(index: int) -> str:
    return f"chunk_{index + 1:03d}"


def agent_id(index: int) -> str:
    return f"agent_{index + 1:03d}"


def layout_block_id(page_index: int, block_index: int) -> str:
    return f"lb_p{page_index + 1:03d}_{block_index + 1:03d}"


def document_id_from_hash(source_hash: str | None) -> str:
    if source_hash and len(source_hash) >= 12:
        return f"doc_{source_hash[:12]}"
    return "doc_001"
