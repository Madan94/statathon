"""Multi-column rule confidence blending (formula from Phase-3 architecture)."""


def multi_column_rule_confidence(
    *,
    relationship_strength: float,
    domain_similarity: float,
    graph_support: float,
    historical_support: float = 0.5,
) -> float:
    rs = max(0.0, min(1.0, relationship_strength))
    ds = max(0.0, min(1.0, domain_similarity))
    gs = max(0.0, min(1.0, graph_support))
    hs = max(0.0, min(1.0, historical_support))
    raw = 0.40 * rs + 0.30 * ds + 0.20 * gs + 0.10 * hs
    return round(raw, 4)
