import pytest


def test_analysis_state_api_payload_structure():
    from core.state import AnalysisState

    state = AnalysisState(
        dataset_id=1,
        analysis_id=2,
        inferred_dataset_context={"dataset_type": "census", "domain_scores": {"census": 0.9}},
        semantic_profile={
            "columns": {
                "age": {"domain": "demographic", "confidence": 0.92},
            }
        },
        semantic_clusters=[{"cluster_id": "cluster_0", "domain": "demographic", "support_score": 0.9, "columns": ["age"]}],
        schema_graph={"nodes": [{"name": "age"}], "edges": []},
        dependency_graph={"income": [{"column": "education", "score": 0.5, "dependency_reason": "test"}]},
        profiling_summary={"rows": 10},
    )
    payload = state.to_api_payload()
    assert payload["dataset_context"]["dataset_type"] == "census"
    assert isinstance(payload["semantic_mapping"], list)
    assert payload["semantic_mapping"][0]["column"] == "age"
    assert payload["clusters"][0]["cluster_id"] == "cluster_0"
    assert isinstance(payload["priority_dependencies"], list)


def test_semantic_adapter_injects_cluster_ids():
    from pipelines.semantic_adapter import build_analysis_state

    pipe = {
        "dataset_context": {"dataset_type": "labor"},
        "semantic_mapping": {"wage": {"domain": "income", "confidence": 0.8}},
        "clusters": [],
        "priority_dependencies": {},
        "schema_graph": {"nodes": [], "edges": []},
        "column_cluster_map": {"wage": "cluster_1"},
        "audit_records": [],
    }
    state = build_analysis_state(
        dataset_id=3,
        analysis_id=4,
        pipeline_out=pipe,
        profiling_summary={},
        dataset_metadata={},
    )
    assert state.semantic_profile["columns"]["wage"]["cluster_id"] == "cluster_1"
