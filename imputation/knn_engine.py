"""KNN imputation fitness from graph + correlation signals (Phase 3C; no fit)."""


def knn_graph_support(column: str, kg_edges: list[dict]) -> float:
    rels = [e for e in kg_edges if column in (e.get("source_column"), e.get("target_column"))]
    if not rels:
        return 0.35
    w = sum(abs(float(e.get("weight") or 0.0)) for e in rels) / max(len(rels), 1)
    return float(max(0.0, min(1.0, w)))


def score_knn(corr_max_abs: float, graph_support: float) -> float:
    corr = max(0.0, min(1.0, abs(float(corr_max_abs))))
    gs = max(0.0, min(1.0, float(graph_support)))
    raw = 0.55 * corr + 0.45 * gs
    return round(max(0.0, min(1.0, raw)), 4)

