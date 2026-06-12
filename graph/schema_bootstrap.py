"""One-time Neo4j schema bootstrap: indexes + constraints.

The first time the application talks to a Neo4j instance the indexes and
unique constraints required by `neo4j_sync.py` and `query_api.py` must
exist. This module idempotently creates them. Callers should invoke
`ensure_schema()` at app startup (or right before the first sync) so that:

  * Column lookups by (analysis_id, name)        are O(log n)
  * Cluster lookups by (analysis_id, cluster_id)  are O(log n)
  * Domain lookups by (analysis_id, slug)         are O(log n)
  * Duplicate columns/clusters/domains can never be inserted by accident.

Also exposes `write_cluster_properties()` to attach cohesion, size, and
human-readable name onto existing `StatathonClusterStub` nodes after the
Phase 5 clustering pass.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def ensure_schema() -> dict[str, Any]:
    """Idempotently create indexes + constraints. Returns a status dict."""
    if os.getenv("NEO4J_ENABLED", "false").lower() != "true":
        return {"enabled": False, "reason": "NEO4J_ENABLED not true"}
    try:
        from neo4j import GraphDatabase  # type: ignore
    except Exception as exc:
        return {"enabled": True, "ok": False, "error": f"neo4j driver missing: {exc}"}

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    if not password:
        return {"enabled": True, "ok": False, "error": "no password"}

    statements = [
        "CREATE CONSTRAINT statathon_col_uniq IF NOT EXISTS "
        "FOR (c:StatathonCol) REQUIRE (c.analysis_id, c.name) IS UNIQUE",
        "CREATE CONSTRAINT statathon_cluster_uniq IF NOT EXISTS "
        "FOR (cl:StatathonClusterStub) REQUIRE (cl.analysis_id, cl.cluster_id) IS UNIQUE",
        "CREATE CONSTRAINT statathon_domain_uniq IF NOT EXISTS "
        "FOR (d:StatathonSemanticDomainStub) REQUIRE (d.analysis_id, d.slug) IS UNIQUE",
        "CREATE CONSTRAINT statathon_dataset_uniq IF NOT EXISTS "
        "FOR (ds:StatathonSemanticDatasetAnchor) REQUIRE ds.analysis_id IS UNIQUE",
        "CREATE INDEX statathon_col_domain IF NOT EXISTS "
        "FOR (c:StatathonCol) ON (c.analysis_id, c.semantic_domain)",
        "CREATE INDEX statathon_col_cluster IF NOT EXISTS "
        "FOR (c:StatathonCol) ON (c.analysis_id, c.cluster_id)",
    ]

    driver = None
    created = 0
    errors: list[str] = []
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database) as sess:
            for stmt in statements:
                try:
                    sess.run(stmt)
                    created += 1
                except Exception as exc:
                    errors.append(f"{stmt[:60]}...: {exc}")
        return {"enabled": True, "ok": not errors, "statements_run": created, "errors": errors}
    except Exception as exc:
        return {"enabled": True, "ok": False, "error": str(exc)}
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception:
                pass


def write_cluster_properties(
    *,
    analysis_id: int,
    cluster_id: str,
    properties: dict[str, Any],
) -> bool:
    """Attach cohesion, semantic_name, size etc. onto a cluster node."""
    if os.getenv("NEO4J_ENABLED", "false").lower() != "true":
        return False
    try:
        from neo4j import GraphDatabase  # type: ignore
    except Exception:
        return False
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    if not password:
        return False
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database) as sess:
            sess.run(
                """
                MERGE (cl:StatathonClusterStub {analysis_id:$aid, cluster_id:$cid})
                SET cl += $props,
                    cl.updated_ts = timestamp()
                """,
                aid=int(analysis_id), cid=str(cluster_id),
                props={k: v for k, v in properties.items() if v is not None},
            )
        return True
    except Exception as exc:
        logger.info("write_cluster_properties failed: %s", exc)
        return False
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception:
                pass
