"""Run graph-conditioned multi-column rule templates."""

from validation.multi_column.relation_engine import extract_column_edges, run_templates_with_confidence


def evaluate_graph_linked_rules(
    *,
    df,
    schema_graph: dict | None,
    priority_dependencies: dict | None,
) -> list[dict]:
    edges = extract_column_edges(schema_graph or {}, priority_dependencies or {})
    runner_factory = run_templates_with_confidence(edges)
    return runner_factory(df)
