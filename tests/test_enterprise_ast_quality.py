"""Quality gate tests for enterprise AST."""
from __future__ import annotations

from template_engine.ast.quality import run_quality_gates


def test_quality_fails_empty_layout():
    report = run_quality_gates(
        {
            "metadata": {"documentId": "d1", "version": "2.0", "checksum": "abc"},
            "layoutAST": {"pages": []},
            "semanticAST": {"nodes": []},
        }
    )
    assert report["passed"] is False
    assert any("layoutAST" in e for e in report["errors"])
