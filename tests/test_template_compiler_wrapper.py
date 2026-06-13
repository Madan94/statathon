"""V0C — Template Compiler Wrapper Integration Test.

Validates that the compiler improves saved output without external services.
"""
import json
import re
from pathlib import Path

import pytest

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "syl_payaluga"


@pytest.fixture
def saved_output():
    ast_path = OUTPUTS_DIR / "template.ast.json"
    bp_path = OUTPUTS_DIR / "template.blueprint.json"
    if not ast_path.exists() or not bp_path.exists():
        pytest.skip("No saved output at outputs/syl_payaluga/")
    return {
        "ast": json.loads(ast_path.read_text(encoding="utf-8")),
        "bp": json.loads(bp_path.read_text(encoding="utf-8")),
    }


class TestTemplateCompilerWrapper:
    """Compiler wrapper improves saved output quality."""

    def test_wrapper_imports(self):
        from report_builder.template_compiler import compile_template_artifacts
        assert compile_template_artifacts is not None

    def test_wrapper_runs(self, saved_output):
        from report_builder.template_compiler import compile_template_artifacts
        result = compile_template_artifacts(raw_ast=saved_output["ast"], blueprint=saved_output["bp"])
        assert "template_ast" in result
        assert "template_blueprint" in result
        assert "diagnostics" in result

    def test_score_improves(self, saved_output):
        from report_builder.template_compiler import compile_template_artifacts
        from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
        from report_builder.value_free_validator import validate_value_free
        from report_builder.extraction_diagnostics import build_extraction_diagnostics

        # Baseline
        bp = saved_output["bp"]
        ast = saved_output["ast"]
        bc = validate_extraction_contract(bp, mode=ExtractionMode.WARN)
        vf = validate_value_free(ast, bp)
        before = build_extraction_diagnostics(blueprint=bp, skeleton=ast, contract_result=bc, value_free_result=vf)

        # After compilation
        result = compile_template_artifacts(raw_ast=ast, blueprint=bp)
        after = result["diagnostics"]

        assert after.binderReadinessScore > before.binderReadinessScore, \
            f"Score should improve: {before.binderReadinessScore} -> {after.binderReadinessScore}"

    def test_no_sequential_ids(self, saved_output):
        from report_builder.template_compiler import compile_template_artifacts
        result = compile_template_artifacts(raw_ast=saved_output["ast"], blueprint=saved_output["bp"])
        entities = result["template_blueprint"].get("entities", [])
        sequential = [e for e in entities if re.match(r'^ent_\d{2,}$', e.get("entityId", ""))]
        assert len(sequential) == 0, f"Sequential IDs remain: {[e['entityId'] for e in sequential[:5]]}"

    def test_aliases_exist(self, saved_output):
        from report_builder.template_compiler import compile_template_artifacts
        result = compile_template_artifacts(raw_ast=saved_output["ast"], blueprint=saved_output["bp"])
        entities = result["template_blueprint"].get("entities", [])
        with_aliases = sum(1 for e in entities if e.get("aliases"))
        assert with_aliases >= len(entities) * 0.8, f"Only {with_aliases}/{len(entities)} have aliases"

    def test_value_domains_exist(self, saved_output):
        from report_builder.template_compiler import compile_template_artifacts
        result = compile_template_artifacts(raw_ast=saved_output["ast"], blueprint=saved_output["bp"])
        entities = result["template_blueprint"].get("entities", [])
        with_domain = sum(1 for e in entities if (e.get("valueDomain") or {}).get("kind") and e.get("valueDomain", {}).get("kind") != "open")
        assert with_domain >= len(entities) * 0.8, f"Only {with_domain}/{len(entities)} have valueDomain"

    def test_value_free_maintained(self, saved_output):
        from report_builder.template_compiler import compile_template_artifacts
        from report_builder.value_free_validator import validate_value_free
        result = compile_template_artifacts(raw_ast=saved_output["ast"], blueprint=saved_output["bp"])
        vf = validate_value_free(result["template_ast"], result["template_blueprint"])
        assert vf.status == "VALID", f"Value-free violated: {[l.code for l in vf.leakages]}"

    def test_diagnostics_serializable(self, saved_output):
        from report_builder.template_compiler import compile_template_artifacts
        result = compile_template_artifacts(raw_ast=saved_output["ast"], blueprint=saved_output["bp"])
        d = result["diagnostics"].to_dict()
        s = json.dumps(d, default=str)
        assert len(s) > 100

    def test_repairs_template_id_mismatch_for_saved_artifacts(self):
        from report_builder.template_compiler import compile_template_artifacts

        ast = {
            "metadata": {"templateId": "tpl_document", "blueprintRef": "tpl_document", "name": "Document"},
            "contentAST": {"blocks": []},
            "tableAST": {"tables": []},
            "chartAST": {"charts": []},
            "figureAST": {"figures": []},
            "semanticAST": {},
            "styleAST": {},
        }
        bp = {
            "templateMeta": {"templateId": "tpl_real", "name": "PLFS", "domain": "labour_force"},
            "entities": [],
            "topics": [],
        }
        result = compile_template_artifacts(raw_ast=ast, blueprint=bp, runtime_trace={"totalCalls": 0})
        assert result["template_ast"]["metadata"]["templateId"] == "tpl_real"
        assert result["template_ast"]["metadata"]["blueprintRef"] == "tpl_real"
        assert result["template_blueprint"]["templateMeta"]["templateId"] == "tpl_real"
        assert "TEMPLATE_ID_MISMATCH" not in {
            e.code for e in result["diagnostics"].blockingErrors
        }
