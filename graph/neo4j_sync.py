"""
Push analysis semantic snapshot into Neo4j (Statathon-scoped subgraph per analysis_id).

Uses MERGE keyed by analysis_id so re-runs overwrite node properties/in-edges cleanly.
Requires: neo4j package + NEO4J_ENABLED=true + valid credentials.
"""
from __future__ import annotations

from typing import Any

from core.state import AnalysisState

from graph.settings import Neo4jSettings


def try_sync_analysis_to_neo4j(state: AnalysisState) -> dict[str, Any]:
    """
    Optionally sync AnalysisState subgraph. Mutates ``state.knowledge_graph`` summary.
    Returns the same summary dict stored on state (never raises — logs failure in summary).
    """
    cfg = Neo4jSettings.from_env()
    if not cfg.enabled:
        summary = {
            "enabled": False,
            "reason": "NEO4J_ENABLED not true",
            "neo4j_uri_masked": "",
        }
        state.knowledge_graph = summary
        state.touch()
        return summary

    if not cfg.password:
        summary = {"enabled": True, "ok": False, "error": "NEO4J_PASSWORD is empty"}
        state.knowledge_graph = summary
        state.touch()
        return summary

    payload = state.to_api_payload()
    semantic_by_col = {row["column"]: row for row in payload.get("semantic_mapping") or [] if "column" in row}
    col_profiles = payload.get("column_profiles") or {}
    deps = payload.get("priority_dependencies") or []
    if isinstance(deps, dict):
        flat: list[dict[str, Any]] = []
        for dependent_column, influencers in deps.items():
            if not isinstance(influencers, list):
                continue
            for inf in influencers:
                if not isinstance(inf, dict):
                    continue
                src = inf.get("column") or inf.get("source_column")
                if not src:
                    continue
                flat.append(
                    {
                        "source_column": src,
                        "dependent_column": dependent_column,
                        "influence_score": inf.get("score") or inf.get("influence_score"),
                        "dependency_reason": inf.get("dependency_reason"),
                    }
                )
        deps = flat

    graph_norm = payload.get("schema_graph") or {}
    edges = graph_norm.get("edges") or []

    ai = payload.get("meta", {}).get("analysis_id") or state.analysis_id
    di = payload.get("meta", {}).get("dataset_id") or state.dataset_id
    fname = (state.dataset_metadata or {}).get("filename") or ""

    try:
        from graph.neo4j_client import neo4j_driver
    except Exception as e:
        summary = {"enabled": True, "ok": False, "error": f"neo4j_import: {e!s}"}
        state.knowledge_graph = summary
        state.touch()
        return summary

    counts = {"columns": 0, "clusters": 0, "domains": 0, "similarity_edges": 0, "influence_edges": 0}

    def work(tx):
        aid = int(ai)
        did = int(di)
        # Drop prior subgraph for this analysis (idempotent sync)
        tx.run(
            """
            MATCH (n:StatathonCol {analysis_id: $aid})
            DETACH DELETE n
            """,
            aid=aid,
        )
        tx.run(
            """
            MATCH (n:StatathonClusterStub {analysis_id: $aid})
            DETACH DELETE n
            """,
            aid=aid,
        )
        tx.run(
            """
            MATCH (n:StatathonSemanticDomainStub {analysis_id: $aid})
            DETACH DELETE n
            """,
            aid=aid,
        )
        tx.run(
            """
            MATCH (n:StatathonSemanticDatasetAnchor {analysis_id: $aid})
            DETACH DELETE n
            """,
            aid=aid,
        )

        tx.run(
            """
            MERGE (ds:StatathonSemanticDatasetAnchor {analysis_id: $aid})
            SET ds.dataset_id = $did,
                ds.filename = $fname,
                ds.dataset_type = $dtype,
                ds.updated_ts = timestamp()
            """,
            aid=aid,
            did=did,
            fname=str(fname),
            dtype=str((payload.get("dataset_context") or {}).get("dataset_type") or ""),
        )

        seen_domains: set[str] = set()
        seen_clusters: set[str] = set()

        for col_name in sorted(semantic_by_col.keys()):
            row = semantic_by_col[col_name]
            prof = col_profiles.get(col_name) or {}
            domain = str(row.get("domain") or "unknown")
            cid = str(row.get("cluster_id") or "")

            tx.run(
                """
                MERGE (c:StatathonCol {analysis_id: $aid, name: $name})
                SET c.semantic_domain = $domain,
                    c.confidence = $confidence,
                    c.cluster_id = $cluster_id,
                    c.datatype = $datatype,
                    c.missing_ratio = $missing_ratio,
                    c.cardinality = $cardinality,
                    c.updated_ts = timestamp()
                MERGE (ds:StatathonSemanticDatasetAnchor {analysis_id: $aid})
                MERGE (c)-[:BELONGS_TO_DATASET]->(ds)
                """,
                aid=aid,
                name=str(col_name),
                domain=domain,
                confidence=row.get("confidence"),
                cluster_id=cid or None,
                datatype=str(prof.get("datatype") or ""),
                missing_ratio=prof.get("missing_ratio"),
                cardinality=prof.get("cardinality"),
            )
            counts["columns"] += 1

            d_key = domain
            seen_domains.add(d_key)
            tx.run(
                """
                MERGE (d:StatathonSemanticDomainStub {analysis_id: $aid, slug: $slug})
                SET d.label = $slug,
                    d.updated_ts = timestamp()
                MERGE (c:StatathonCol {analysis_id: $aid, name: $col})
                MERGE (c)-[tg:TAGGED_DOMAIN]->(d)
                SET tg.confidence = $confidence,
                    tg.updated_ts = timestamp()
                """,
                aid=aid,
                slug=d_key,
                col=str(col_name),
                confidence=float(row.get("confidence") or 0.0),
            )

            if cid:
                seen_clusters.add(cid)
                tx.run(
                    """
                    MERGE (cl:StatathonClusterStub {analysis_id: $aid, cluster_id: $cluster_id})
                    SET cl.updated_ts = timestamp()
                    MERGE (c:StatathonCol {analysis_id: $aid, name: $col})
                    MERGE (c)-[:PART_OF_CLUSTER]->(cl)
                    """,
                    aid=aid,
                    cluster_id=cid,
                    col=str(col_name),
                )

        counts["domains"] = len(seen_domains)
        counts["clusters"] = len(seen_clusters)

        for e in edges:
            if not isinstance(e, dict):
                continue
            s = e.get("source")
            t = e.get("target")
            if not s or not t:
                continue
            tx.run(
                """
                MATCH (a:StatathonCol {analysis_id: $aid, name: $s})
                MATCH (b:StatathonCol {analysis_id: $aid, name: $t})
                MERGE (a)-[r:SEMANTICALLY_SIMILAR]->(b)
                SET r.weight = $weight,
                    r.relationship_type = coalesce($rtype, 'semantic_similarity'),
                    r.semantic_reason = $why,
                    r.updated_ts = timestamp()
                """,
                aid=aid,
                s=str(s),
                t=str(t),
                weight=float(e.get("weight") or 0.0),
                rtype=e.get("relationship_type"),
                why=e.get("semantic_reason") or "",
            )
            counts["similarity_edges"] += 1

        for edge in deps:
            if not isinstance(edge, dict):
                continue
            src = edge.get("source_column")
            dep = edge.get("dependent_column")
            if not src or not dep:
                continue
            tx.run(
                """
                MATCH (a:StatathonCol {analysis_id: $aid, name: $src})
                MATCH (b:StatathonCol {analysis_id: $aid, name: $dep})
                MERGE (a)-[r:CONTEXT_INFLUENCES]->(b)
                SET r.score = $score,
                    r.dependency_reason = $why,
                    r.updated_ts = timestamp()
                """,
                aid=aid,
                src=str(src),
                dep=str(dep),
                score=float(edge.get("influence_score") or 0.0),
                why=str(edge.get("dependency_reason") or ""),
            )
            counts["influence_edges"] += 1

    try:
        driver = neo4j_driver(cfg)
        try:
            with driver.session(database=cfg.database) as session:
                session.execute_write(work)
        finally:
            driver.close()

        masked = cfg.uri.split("@")[-1] if "@" in cfg.uri else cfg.uri
        summary = {
            "enabled": True,
            "ok": True,
            "database": cfg.database,
            "neo4j_uri_masked": masked,
            "counts": counts,
        }
    except Exception as e:
        summary = {
            "enabled": True,
            "ok": False,
            "error": str(e),
            "counts": counts,
        }

    state.knowledge_graph = summary
    state.touch()
    return summary
