"""Enterprise AST v2.0 schema and migration tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from template_engine.ast.enterprise_schema import EnterpriseDocumentAST
from template_engine.ast.migration_v1 import is_enterprise_ast, migrate_v1_blocks_to_enterprise
from template_engine.ast.quality import run_quality_gates, stable_checksum


def test_enterprise_roundtrip_minimal():
    doc = EnterpriseDocumentAST()
    doc.metadata.documentId = "doc_test"
    doc.metadata.version = "2.0"
    doc.metadata.checksum = ""
    doc.semanticAST.nodes = [
        {
            "id": "section_001",
            "type": "section",
            "title": "Intro",
            "kind": "narrative",
            "children": [],
        }
    ]
    doc.layoutAST.pages = [{"pageId": "page_001", "width": 612, "height": 792, "blocks": []}]
    doc.contentAST.paragraphs = [{"id": "p_001", "type": "paragraph", "content": "Hello"}]
    payload = doc.to_dict()
    payload["metadata"]["checksum"] = stable_checksum(payload)
    restored = EnterpriseDocumentAST.from_dict(payload)
    assert restored.metadata.documentId == "doc_test"
    assert len(restored.semanticAST.nodes) == 1


def test_migrate_v1_blocks():
    v1 = {
        "name": "Test",
        "blocks": [
            {
                "block_id": "exec_summary",
                "kind": "narrative",
                "title": "Executive Summary",
                "section": "executive_summary",
                "required": True,
                "hints": {},
            }
        ],
    }
    out = migrate_v1_blocks_to_enterprise(v1, template_name="Test")
    assert is_enterprise_ast(out)
    assert out["metadata"]["version"] == "2.0"
    assert len(out["semanticAST"]["nodes"]) >= 1
    quality = run_quality_gates(out)
    assert quality["passed"] is True


def test_energy_fixture_import():
    path = Path(__file__).resolve().parent.parent / "test_data" / "ast.json.txt"
    if not path.exists():
        pytest.skip("ast.json.txt not present")
    raw = json.loads(path.read_text(encoding="utf-8"))
    from report_builder.energy_ast_converter import import_energy_chapter_ast

    doc = import_energy_chapter_ast(raw)
    assert is_enterprise_ast(doc)
    assert len(doc.get("semanticAST", {}).get("nodes") or []) > 0
