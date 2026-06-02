"""Neo4j read-side API.

Until now `graph/neo4j_sync.py` was write-only — nothing read back from the
graph. This module adds the traversal helpers that the validation and
imputation subsystems need to reason about column relationships *via the
graph* rather than re-deriving them from the analysis payload every time.

Public surface:
    GraphQueryClient(analysis_id).neighbors_of(column, k=2)
    GraphQueryClient(analysis_id).path_between(col_a, col_b)
    GraphQueryClient(analysis_id).cluster_members(cluster_id)
    GraphQueryClient(analysis_id).domain_of(column)
    GraphQueryClient(analysis_id).columns_in_domain(domain, limit=20)
    GraphQueryClient(analysis_id).edge_weight(col_a, col_b)

Every method degrades gracefully (returns []/None) if Neo4j is unreachable
or n10s is missing — callers should always get a *typed* response, never
an exception that would bubble into a pipeline failure.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def neo4j_enabled() -> bool:
    return os.getenv("NEO4J_ENABLED", "false").lower() == "true"


@contextmanager
def _session() -> Iterator[Any | None]:
    if not neo4j_enabled():
        yield None
        return
    try:
        from neo4j import GraphDatabase  # type: ignore
    except Exception:
        yield None
        return
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    if not password:
        yield None
        return
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database) as session:
            yield session
    except Exception as exc:
        logger.info("Neo4j session unavailable: %s", exc)
        yield None
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception:
                pass


class GraphQueryClient:
    """Reads structured data out of the analysis subgraph."""

    def __init__(self, analysis_id: int):
        self.analysis_id = int(analysis_id)

    # ---------------- ergonomic helpers ----------------

    def _column_id(self, column: str) -> str:
        return f"{self.analysis_id}::{column}"

    def neighbors_of(self, column: str, k: int = 2, min_weight: float = 0.0
                     ) -> list[dict[str, Any]]:
        """k-hop neighbours of a column, ordered by descending edge weight."""
        with _session() as sess:
            if sess is None:
                return []
            try:
                rows = sess.run(
                    """
                    MATCH (c:StatathonCol {analysis_id:$aid, name:$col})
                    MATCH (c)-[r:SEMANTICALLY_SIMILAR|CONTEXT_INFLUENCES*1..$k]-(o:StatathonCol)
                    WITH o, [x IN r | x.weight] AS weights
                    WITH o.name AS name,
                         o.semantic_domain AS domain,
                         REDUCE(s = 1.0, w IN weights | s * coalesce(w, 0.5)) AS path_weight
                    WHERE path_weight >= $min_weight
                    RETURN name, domain, path_weight
                    ORDER BY path_weight DESC LIMIT 50
                    """,
                    aid=self.analysis_id, col=column, k=int(k),
                    min_weight=float(min_weight),
                )
                return [
                    {"column": r["name"], "domain": r["domain"],
                     "weight": float(r["path_weight"])}
                    for r in rows
                ]
            except Exception as exc:
                logger.info("neighbors_of(%s) failed: %s", column, exc)
                return []

    def path_between(self, col_a: str, col_b: str, max_hops: int = 4
                     ) -> list[dict[str, Any]]:
        """Shortest weighted path between two columns (if any)."""
        with _session() as sess:
            if sess is None:
                return []
            try:
                rec = sess.run(
                    """
                    MATCH (a:StatathonCol {analysis_id:$aid, name:$a})
                    MATCH (b:StatathonCol {analysis_id:$aid, name:$b})
                    MATCH p = shortestPath((a)-[*..$h]-(b))
                    RETURN [n IN nodes(p) | n.name] AS hops,
                           length(p) AS len
                    """,
                    aid=self.analysis_id, a=col_a, b=col_b, h=int(max_hops),
                ).single()
                if rec is None:
                    return []
                return [
                    {"column": h, "step": i}
                    for i, h in enumerate(rec["hops"] or [])
                ]
            except Exception as exc:
                logger.info("path_between(%s,%s) failed: %s", col_a, col_b, exc)
                return []

    def cluster_members(self, cluster_id: str) -> list[str]:
        with _session() as sess:
            if sess is None:
                return []
            try:
                rows = sess.run(
                    """
                    MATCH (cl:StatathonClusterStub {analysis_id:$aid, cluster_id:$cid})
                    MATCH (col:StatathonCol)-[:PART_OF_CLUSTER]->(cl)
                    RETURN col.name AS name
                    """,
                    aid=self.analysis_id, cid=str(cluster_id),
                )
                return [r["name"] for r in rows if r and r.get("name")]
            except Exception:
                return []

    def domain_of(self, column: str) -> str | None:
        with _session() as sess:
            if sess is None:
                return None
            try:
                rec = sess.run(
                    """
                    MATCH (c:StatathonCol {analysis_id:$aid, name:$col})
                    RETURN c.semantic_domain AS domain LIMIT 1
                    """,
                    aid=self.analysis_id, col=column,
                ).single()
                return rec["domain"] if rec else None
            except Exception:
                return None

    def columns_in_domain(self, domain: str, limit: int = 20) -> list[str]:
        with _session() as sess:
            if sess is None:
                return []
            try:
                rows = sess.run(
                    """
                    MATCH (c:StatathonCol {analysis_id:$aid})
                    WHERE c.semantic_domain = $domain
                    RETURN c.name AS name LIMIT $lim
                    """,
                    aid=self.analysis_id, domain=domain, lim=int(limit),
                )
                return [r["name"] for r in rows if r and r.get("name")]
            except Exception:
                return []

    def edge_weight(self, col_a: str, col_b: str) -> float | None:
        with _session() as sess:
            if sess is None:
                return None
            try:
                rec = sess.run(
                    """
                    MATCH (a:StatathonCol {analysis_id:$aid, name:$a})
                          -[r:SEMANTICALLY_SIMILAR|CONTEXT_INFLUENCES]-
                          (b:StatathonCol {analysis_id:$aid, name:$b})
                    RETURN coalesce(r.weight, r.score, 0.5) AS w LIMIT 1
                    """,
                    aid=self.analysis_id, a=col_a, b=col_b,
                ).single()
                return float(rec["w"]) if rec else None
            except Exception:
                return None


# ---------------------------------------------------------------------------
# In-memory fallback (when Neo4j is offline or NEO4J_ENABLED=false)
# ---------------------------------------------------------------------------


class PayloadGraphFallback:
    """Same surface as `GraphQueryClient` but reads from the analysis payload.

    Used by validation / imputation when Neo4j is not available so they can
    still exploit column-relationship signals.
    """

    def __init__(self, payload: dict[str, Any]):
        sg = payload.get("schema_graph") or {}
        self._edges = sg.get("edges") if isinstance(sg, dict) else []
        self._deps = payload.get("priority_dependencies") or {}
        self._domain_by_col: dict[str, str] = {}
        for row in payload.get("semantic_mapping") or []:
            if isinstance(row, dict) and row.get("column"):
                self._domain_by_col[str(row["column"])] = str(
                    row.get("domain") or row.get("semantic_domain") or "")

    def neighbors_of(self, column: str, k: int = 2,
                     min_weight: float = 0.0) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in self._edges or []:
            if not isinstance(e, dict):
                continue
            if e.get("source") == column or e.get("target") == column:
                other = e.get("target") if e.get("source") == column else e.get("source")
                w = float(e.get("weight") or 0.0)
                if w >= min_weight:
                    out.append({
                        "column": other,
                        "domain": self._domain_by_col.get(other or "", ""),
                        "weight": w,
                    })
        out.sort(key=lambda r: r["weight"], reverse=True)
        return out[:50]

    def domain_of(self, column: str) -> str | None:
        return self._domain_by_col.get(column)

    def columns_in_domain(self, domain: str, limit: int = 20) -> list[str]:
        out = [c for c, d in self._domain_by_col.items() if d == domain]
        return out[:limit]

    def edge_weight(self, col_a: str, col_b: str) -> float | None:
        for e in self._edges or []:
            if not isinstance(e, dict):
                continue
            if {e.get("source"), e.get("target")} == {col_a, col_b}:
                return float(e.get("weight") or 0.0)
        return None

    def cluster_members(self, cluster_id: str) -> list[str]:
        # No cluster info in plain payload — return []
        return []

    def path_between(self, col_a: str, col_b: str, max_hops: int = 4
                     ) -> list[dict[str, Any]]:
        # Trivial BFS over edges
        if col_a == col_b:
            return [{"column": col_a, "step": 0}]
        adj: dict[str, list[str]] = {}
        for e in self._edges or []:
            if not isinstance(e, dict):
                continue
            s, t = e.get("source"), e.get("target")
            if not s or not t:
                continue
            adj.setdefault(s, []).append(t)
            adj.setdefault(t, []).append(s)
        if col_a not in adj or col_b not in adj:
            return []
        from collections import deque

        prev: dict[str, str | None] = {col_a: None}
        q = deque([col_a])
        while q:
            cur = q.popleft()
            if cur == col_b:
                break
            for nxt in adj.get(cur, []):
                if nxt in prev:
                    continue
                prev[nxt] = cur
                q.append(nxt)
        if col_b not in prev:
            return []
        path = []
        cur: str | None = col_b
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        if len(path) - 1 > max_hops:
            return []
        return [{"column": c, "step": i} for i, c in enumerate(path)]


def make_graph_client(analysis_id: int, payload_fallback: dict[str, Any] | None = None):
    """Factory: returns Neo4j-backed client if available, else payload fallback."""
    if neo4j_enabled():
        try:
            client = GraphQueryClient(analysis_id)
            # Smoke test connectivity quickly
            with _session() as sess:
                if sess is not None:
                    return client
        except Exception:
            pass
    if payload_fallback is not None:
        return PayloadGraphFallback(payload_fallback)
    return PayloadGraphFallback({})
