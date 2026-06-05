"""Render reports from enterprise AST v2.0 (semanticAST-driven)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from report_builder.agui import RenderedBlock
from template_engine.ast.enterprise_schema import EnterpriseDocumentAST, SemanticNode
from template_engine.ast.migration_v1 import is_enterprise_ast, migrate_v1_blocks_to_enterprise

logger = logging.getLogger(__name__)


@dataclass
class _RenderBlock:
    """Adapter so pipeline block renderers accept enterprise semantic nodes."""

    block_id: str
    kind: str
    title: str
    section: str
    required: bool = True
    hints: dict[str, Any] = field(default_factory=dict)


def _walk_semantic_nodes(nodes: list[SemanticNode]) -> list[_RenderBlock]:
    out: list[_RenderBlock] = []

    def walk(ns: list[SemanticNode]) -> None:
        for n in ns:
            section = str(n.hints.get("section") or "general")
            hints = dict(n.hints)
            if n.contentRef:
                hints.setdefault("contentRef", n.contentRef)
            if n.tableRef:
                hints.setdefault("tableRef", n.tableRef)
                hints.setdefault("source", hints.get("source") or "semantic_mapping")
            out.append(
                _RenderBlock(
                    block_id=n.id,
                    kind=n.kind,
                    title=n.title,
                    section=section,
                    required=n.required,
                    hints=hints,
                )
            )
            walk(n.children)

    walk(nodes)
    return out


def _agent_scope_for_node(agent_ast: dict[str, Any], node_id: str) -> dict[str, Any]:
    agents = (agent_ast or {}).get("agents") or []
    for ag in agents:
        if not isinstance(ag, dict):
            continue
        visible = ag.get("visibleNodes") or []
        if not visible or node_id in visible:
            return ag
    return {}


class EnterpriseReportRenderer:
    """Depth-first render of semanticAST nodes using pipeline block renderers."""

    def __init__(self, template_ast: dict[str, Any]) -> None:
        if not is_enterprise_ast(template_ast):
            template_ast = migrate_v1_blocks_to_enterprise(template_ast)
        self.doc = EnterpriseDocumentAST.from_dict(template_ast)
        self.payload = template_ast

    @property
    def template_name(self) -> str:
        return self.doc.metadata.name or "Report"

    def iter_render_blocks(self) -> list[_RenderBlock]:
        return _walk_semantic_nodes(self.doc.semanticAST.nodes)

    def render_all(
        self,
        *,
        analysis_payload: dict[str, Any],
        facts: dict[str, Any],
        df: pd.DataFrame,
        kg_result: Any,
        ledger: Any,
        render_block_fn: Callable[..., dict[str, Any]],
        classify_intent_fn: Callable[..., Any],
        verify_block_fn: Callable[..., Any] | None = None,
    ) -> tuple[list[RenderedBlock], dict[str, Any]]:
        rendered: list[RenderedBlock] = []
        verifier_report: dict[str, Any] = {"blocks": [], "schema_version": "2.0"}
        agent_payload = self.doc.agentAST.model_dump(mode="json")

        for block in self.iter_render_blocks():
            scope = _agent_scope_for_node(agent_payload, block.block_id)
            enriched_hints = dict(block.hints)
            if scope:
                enriched_hints["_agent_scope"] = scope
            block.hints = enriched_hints

            route = classify_intent_fn(block.kind, block.hints or {})
            payload = render_block_fn(block, analysis_payload, facts, df, kg_result, ledger)

            verifier_dict: dict[str, Any] | None = None
            if block.kind == "narrative" and payload.get("text") and verify_block_fn:
                verdict = verify_block_fn(
                    block_id=block.block_id,
                    narrative=payload["text"],
                    df=df if not df.empty else None,
                    expected_facts=facts,
                )
                verifier_dict = verdict.to_dict() if hasattr(verdict, "to_dict") else verdict
                verifier_report["blocks"].append(verifier_dict)

            style_hints = {}
            if self.doc.styleAST.styles:
                style_hints["style_count"] = len(self.doc.styleAST.styles)
            if self.doc.geometryAST.nodes:
                style_hints["geometry_nodes"] = min(len(self.doc.geometryAST.nodes), 50)

            rendered.append(
                RenderedBlock(
                    block_id=block.block_id,
                    kind=block.kind,
                    title=block.title,
                    section=block.section,
                    payload={**payload, "_enterprise": style_hints},
                    verifier=verifier_dict,
                    route={"engine": route.kind, "rationale": route.rationale},
                )
            )

        return rendered, verifier_report
