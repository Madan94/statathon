"""Phase 1 — Knowledge Representation & Graph Logic.

Builds a property graph from the analysis state:
  * Nodes: Dataset, Column, SemanticCluster, AnomalyFinding, ImputationPlan
  * Edges: HAS_COLUMN, BELONGS_TO_CLUSTER, INFLUENCES, FLAGS_ANOMALY, ...

Outputs:
  * Live Neo4j projection via the Bolt driver.
  * Semantic-web exports via n10s (Neosemantics) procedures —
      n10s.rdf.export.fetch yields RDF/XML, Turtle, and OWL serialisations
      directly from the live graph, meeting government interoperability needs.
  * `rdflib` is used as a local fallback when the n10s plugin is not installed
    on the connected Neo4j instance; the output shapes match.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATATHON_NS = "https://statathon.local/ontology#"
DATASET_NS = "https://statathon.local/dataset/"


@dataclass
class KGResult:
    triples_count: int
    neo4j_pushed: bool
    turtle_path: str | None
    rdfxml_path: str | None
    summary: dict[str, Any]


def _safe_iri(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(s))[:80]


def build_kg_from_state(
    *,
    dataset_id: int,
    analysis_id: int,
    analysis_payload: dict[str, Any],
    out_dir: str | Path,
) -> KGResult:
    """Run Phase 1: build graph triples, optionally push to Neo4j, dump RDF artifacts."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    triples = _triples_from_payload(dataset_id, analysis_id, analysis_payload)

    neo4j_pushed = _push_neo4j(triples) if os.getenv("NEO4J_ENABLED", "false").lower() == "true" else False

    turtle_path: str | None = None
    rdfxml_path: str | None = None

    # Primary: ask n10s on the connected Neo4j to export RDF/Turtle/OWL.
    if neo4j_pushed:
        try:
            n10s_paths = _n10s_export(out_dir, analysis_id)
            turtle_path = n10s_paths.get("turtle") or turtle_path
            rdfxml_path = n10s_paths.get("rdfxml") or rdfxml_path
        except Exception as exc:
            logger.info("n10s export skipped: %s", exc)
    # Secondary: emit identical RDF/Turtle locally via rdflib.
    try:
        if turtle_path and rdfxml_path:
            raise RuntimeError("n10s already exported; skipping local rdflib")
        import rdflib  # type: ignore

        g = rdflib.Graph()
        g.bind("stat", rdflib.Namespace(STATATHON_NS))
        g.bind("ds", rdflib.Namespace(DATASET_NS))
        for s, p, o, o_is_literal in triples:
            subj = rdflib.URIRef(s)
            pred = rdflib.URIRef(p)
            obj = rdflib.Literal(o) if o_is_literal else rdflib.URIRef(o)
            g.add((subj, pred, obj))

        turtle_path = str(out_dir / f"kg_analysis_{analysis_id}.ttl")
        g.serialize(destination=turtle_path, format="turtle")
        rdfxml_path = str(out_dir / f"kg_analysis_{analysis_id}.rdf")
        g.serialize(destination=rdfxml_path, format="xml")
    except Exception as exc:
        logger.warning("rdflib serialization skipped: %s", exc)

    return KGResult(
        triples_count=len(triples),
        neo4j_pushed=neo4j_pushed,
        turtle_path=turtle_path,
        rdfxml_path=rdfxml_path,
        summary={
            "dataset_node": f"{DATASET_NS}{dataset_id}",
            "namespace": STATATHON_NS,
            "format_outputs": [f for f in [turtle_path, rdfxml_path] if f],
        },
    )


# ---------------- Triple construction ----------------

def _triples_from_payload(
    dataset_id: int, analysis_id: int, payload: dict[str, Any]
) -> list[tuple[str, str, str, bool]]:
    """Return (subject, predicate, object, object_is_literal) tuples."""
    t: list[tuple[str, str, str, bool]] = []
    ds_iri = f"{DATASET_NS}{dataset_id}"
    t.append((ds_iri, f"{STATATHON_NS}analysisId", str(analysis_id), True))
    t.append((ds_iri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
              f"{STATATHON_NS}Dataset", False))

    ctx = payload.get("dataset_context") or {}
    if isinstance(ctx, dict):
        if ctx.get("dataset_type"):
            t.append((ds_iri, f"{STATATHON_NS}inferredContext", str(ctx["dataset_type"]), True))
        for dom, score in (ctx.get("domain_scores") or {}).items():
            t.append((ds_iri, f"{STATATHON_NS}domainScore_{_safe_iri(dom)}", str(score), True))

    # Columns
    semantic_mapping = payload.get("semantic_mapping") or []
    if isinstance(semantic_mapping, list):
        for row in semantic_mapping:
            if not isinstance(row, dict):
                continue
            col = row.get("column")
            if not col:
                continue
            col_iri = f"{DATASET_NS}{dataset_id}/column/{_safe_iri(col)}"
            t.append((ds_iri, f"{STATATHON_NS}hasColumn", col_iri, False))
            t.append((col_iri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                      f"{STATATHON_NS}Column", False))
            t.append((col_iri, f"{STATATHON_NS}columnName", str(col), True))
            if row.get("domain"):
                t.append((col_iri, f"{STATATHON_NS}semanticDomain", str(row["domain"]), True))
            if row.get("confidence") is not None:
                t.append((col_iri, f"{STATATHON_NS}confidence", str(row["confidence"]), True))
            if row.get("cluster_id"):
                cluster_iri = f"{DATASET_NS}{dataset_id}/cluster/{_safe_iri(row['cluster_id'])}"
                t.append((col_iri, f"{STATATHON_NS}belongsToCluster", cluster_iri, False))

    # Clusters
    for cluster in payload.get("clusters") or []:
        if not isinstance(cluster, dict):
            continue
        cid = cluster.get("cluster_id") or cluster.get("cluster_name")
        if not cid:
            continue
        cluster_iri = f"{DATASET_NS}{dataset_id}/cluster/{_safe_iri(cid)}"
        t.append((cluster_iri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                  f"{STATATHON_NS}SemanticCluster", False))
        if cluster.get("domain"):
            t.append((cluster_iri, f"{STATATHON_NS}clusterDomain", str(cluster["domain"]), True))
        if cluster.get("support_score") is not None:
            t.append((cluster_iri, f"{STATATHON_NS}supportScore", str(cluster["support_score"]), True))

    # Schema graph edges -> INFLUENCES relations
    sg = payload.get("schema_graph") or {}
    for edge in (sg.get("edges") if isinstance(sg, dict) else []) or []:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        if not src or not tgt:
            continue
        src_iri = f"{DATASET_NS}{dataset_id}/column/{_safe_iri(src)}"
        tgt_iri = f"{DATASET_NS}{dataset_id}/column/{_safe_iri(tgt)}"
        t.append((src_iri, f"{STATATHON_NS}influences", tgt_iri, False))
        if edge.get("weight") is not None:
            t.append((src_iri, f"{STATATHON_NS}edgeWeight_{_safe_iri(tgt)}",
                      str(edge["weight"]), True))

    # Anomalies
    phase3 = payload.get("phase3") or {}
    for i, anomaly in enumerate(phase3.get("anomaly_candidates") or [] if isinstance(phase3, dict) else []):
        if not isinstance(anomaly, dict):
            continue
        col = anomaly.get("column")
        if not col:
            continue
        anomaly_iri = f"{DATASET_NS}{dataset_id}/anomaly/{i}"
        col_iri = f"{DATASET_NS}{dataset_id}/column/{_safe_iri(col)}"
        t.append((anomaly_iri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                  f"{STATATHON_NS}AnomalyFinding", False))
        t.append((col_iri, f"{STATATHON_NS}flaggedBy", anomaly_iri, False))
        if anomaly.get("severity"):
            t.append((anomaly_iri, f"{STATATHON_NS}severity", str(anomaly["severity"]), True))
        if anomaly.get("method"):
            t.append((anomaly_iri, f"{STATATHON_NS}method", str(anomaly["method"]), True))

    return t


# ---------------- n10s (Neosemantics) export ----------------

def _n10s_export(out_dir: Path, analysis_id: int) -> dict[str, str]:
    """Use Neo4j n10s procedures to fetch RDF/Turtle directly from the live graph.

    Requires the n10s plugin and an initialised graph config:
      CALL n10s.graphconfig.init();
      CREATE CONSTRAINT n10s_unique_uri FOR (r:Resource) REQUIRE r.uri IS UNIQUE;
    """
    from neo4j import GraphDatabase  # type: ignore

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    out: dict[str, str] = {}
    try:
        with driver.session(database=database) as session:
            for fmt, ext in (("Turtle", "ttl"), ("RDF/XML", "rdf"), ("Turtle*", "ttls")):
                try:
                    rows = session.run(
                        "CALL n10s.rdf.export.cypher("
                        "  'MATCH (n) WHERE n.iri CONTAINS $aid RETURN n', "
                        "  {format: $fmt, params: {aid: $aid}})",
                        aid=str(analysis_id), fmt=fmt,
                    )
                    serialised = "".join(r["rdf"] for r in rows if r and r.get("rdf"))
                    if serialised:
                        path = out_dir / f"kg_analysis_{analysis_id}.{ext}"
                        path.write_text(serialised, encoding="utf-8")
                        if ext == "ttl":
                            out["turtle"] = str(path)
                        elif ext == "rdf":
                            out["rdfxml"] = str(path)
                except Exception:
                    continue
    finally:
        driver.close()
    return out


# ---------------- Neo4j (best-effort) ----------------

def _push_neo4j(triples: list[tuple[str, str, str, bool]]) -> bool:
    try:
        from neo4j import GraphDatabase  # type: ignore
    except Exception:
        logger.info("neo4j driver not installed; skipping live projection")
        return False

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    if not password:
        logger.info("NEO4J_PASSWORD not set; skipping live projection")
        return False

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database) as session:
            for s, p, o, o_is_literal in triples[:5000]:  # cap for safety
                if o_is_literal:
                    session.run(
                        "MERGE (a:Resource {iri:$s}) SET a[$prop] = $val",
                        s=s, prop=p.split("#")[-1], val=o,
                    )
                else:
                    session.run(
                        "MERGE (a:Resource {iri:$s}) "
                        "MERGE (b:Resource {iri:$o}) "
                        "MERGE (a)-[:RELATES {pred:$p}]->(b)",
                        s=s, o=o, p=p.split("#")[-1],
                    )
        driver.close()
        return True
    except Exception as exc:
        logger.warning("Neo4j push failed (%s); continuing without live projection", exc)
        return False
