def narrative_from_stats(stats: dict) -> str:
    parts = []
    for k, v in stats.items():
        if isinstance(v, (int, float)):
            parts.append(f"{k}: {v:.4g}" if isinstance(v, float) else f"{k}: {v}")
    return "Summary. " + "; ".join(parts) if parts else "No narrative."