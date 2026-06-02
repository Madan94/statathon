"""RetrievalAgent — multi-source data retrieval for the DeepAgent pipeline.

Retrieves from five sources in parallel (best-effort):

1. Dataset    — Arrow/pandas kernel (DuckDB SQL + filter pushdown)
2. KG         — Neo4j / PayloadGraphFallback traversal
3. Rulebooks  — Qdrant (MoSPI methodology notes) / SQLite fallback
4. History    — Qdrant LTM (past reports + human corrections)
5. Validation — Phase3 anomaly + imputation candidates from analysis payload

All sources are optional; missing sources return empty results rather than
raising so the AnalyticsAgent always receives a well-typed RetrievalBundle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RetrievalBundle:
    """Everything the AnalyticsAgent needs."""
    df: pd.DataFrame                          # filtered dataset slice
    kg_neighbors: list[dict[str, Any]]        # related columns from KG
    kg_paths: list[dict[str, Any]]            # cross-column paths
    rulebook_chunks: list[dict[str, Any]]     # methodology / validation rules
    history_chunks: list[dict[str, Any]]      # past reports + corrections
    anomaly_candidates: list[dict[str, Any]]
    imputation_candidates: list[dict[str, Any]]
    validation_candidates: list[dict[str, Any]]
    resolved_columns: list[str]               # columns identified for this query
    domain_columns: dict[str, list[str]]      # domain → column list

    def context_summary(self) -> str:
        """Compact text summary injected into Scribe prompts."""
        parts: list[str] = []
        if not self.df.empty:
            parts.append(f"Dataset: {len(self.df)} rows × {len(self.df.columns)} cols")
        if self.resolved_columns:
            parts.append(f"Target columns: {', '.join(self.resolved_columns[:10])}")
        if self.kg_neighbors:
            related = [n.get("column", "") for n in self.kg_neighbors[:5]]
            parts.append(f"KG neighbors: {', '.join(related)}")
        if self.rulebook_chunks:
            snippets = [r.get("text", "")[:80] for r in self.rulebook_chunks[:2]]
            parts.append("Rulebook: " + "; ".join(snippets))
        if self.anomaly_candidates:
            parts.append(f"Anomalies: {len(self.anomaly_candidates)} flagged")
        if self.imputation_candidates:
            parts.append(f"Imputation targets: {len(self.imputation_candidates)}")
        return " | ".join(parts)


class RetrievalAgent:
    """Fetches data from all relevant sources given an ExecutionPlan."""

    # ── Dataset retrieval ──────────────────────────────────────────────────

    def _fetch_dataset(
        self,
        analysis_id: int,
        df_loader: Callable[[], pd.DataFrame],
        target_columns: list[str],
        target_domains: list[str],
        analysis_payload: dict[str, Any],
    ) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
        """Return (filtered_df, resolved_columns, domain_map)."""
        try:
            from report_builder import kernel as kx
            df = kx.ensure_loaded(analysis_id, df_loader)
        except Exception as exc:
            logger.warning("Dataset load failed: %s", exc)
            try:
                df = df_loader()
            except Exception:
                return pd.DataFrame(), [], {}

        # Build domain → columns map from semantic_mapping
        domain_map: dict[str, list[str]] = {}
        for row in analysis_payload.get("semantic_mapping") or []:
            if not isinstance(row, dict):
                continue
            col = str(row.get("column") or "")
            dom = str(row.get("domain") or row.get("semantic_domain") or "unknown")
            if col:
                domain_map.setdefault(dom, []).append(col)

        # Resolve target columns
        resolved = list(target_columns)
        if not resolved and target_domains:
            for d in target_domains:
                resolved += domain_map.get(d, [])
        # Fuzzy fallback — include columns from all matching domains
        if not resolved:
            resolved = [c for c in df.columns]
        resolved = [c for c in resolved if c in df.columns][:30]

        # Slice to relevant columns (keep all if no specific target)
        slice_df = df[resolved] if resolved and set(resolved) <= set(df.columns) else df

        return slice_df, resolved, domain_map

    # ── KG retrieval ───────────────────────────────────────────────────────

    def _fetch_kg(
        self,
        analysis_id: int,
        analysis_payload: dict[str, Any],
        target_columns: list[str],
        target_domains: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Returns (neighbors, paths)."""
        try:
            from graph.query_api import make_graph_client
            gc = make_graph_client(analysis_id, payload_fallback=analysis_payload)
        except Exception as exc:
            logger.info("KG client init failed: %s", exc)
            return [], []

        neighbors: list[dict[str, Any]] = []
        paths: list[dict[str, Any]] = []

        for col in target_columns[:5]:
            try:
                nbrs = gc.neighbors_of(col, k=2) or []
                for n in nbrs:
                    n["source_column"] = col
                neighbors.extend(nbrs[:10])
            except Exception:
                pass

        # Also pull all columns in target domains
        for dom in target_domains[:3]:
            try:
                dom_cols = gc.columns_in_domain(dom, limit=15) or []
                for c in dom_cols:
                    if not any(n.get("column") == c for n in neighbors):
                        neighbors.append({"column": c, "domain": dom, "weight": 0.5})
            except Exception:
                pass

        # Cross-domain paths (first pair of target columns)
        if len(target_columns) >= 2:
            try:
                p = gc.path_between(target_columns[0], target_columns[1]) or []
                paths = p
            except Exception:
                pass

        return neighbors[:50], paths

    # ── Rulebook retrieval ─────────────────────────────────────────────────

    def _fetch_rulebooks(
        self,
        query: str,
        target_domains: list[str],
        db=None,
    ) -> list[dict[str, Any]]:
        """Retrieve MoSPI methodology rules via Qdrant / Postgres fallback."""
        chunks: list[dict[str, Any]] = []

        # Try Qdrant
        try:
            from report_builder.memory import _qdrant_client, _embed_text, _QDRANT_COLLECTION
            qc = _qdrant_client()
            if qc:
                vec = _embed_text(f"methodology {' '.join(target_domains)} {query}")
                if vec:
                    hits = qc.search(
                        collection_name=_QDRANT_COLLECTION,
                        query_vector=vec,
                        limit=5,
                        query_filter={"must": [{"key": "kind", "match": {"value": "rulebook"}}]}
                        if target_domains else None,
                    )
                    for h in hits:
                        chunks.append({
                            "text": h.payload.get("after") or h.payload.get("before") or "",
                            "domain": h.payload.get("domain", ""),
                            "score": h.score,
                        })
        except Exception as exc:
            logger.debug("Rulebook Qdrant retrieval: %s", exc)

        # Fallback: validation rule library JSON
        if not chunks:
            try:
                import json
                import os
                from pathlib import Path
                rule_path = Path(__file__).resolve().parents[1] / "model" / "config" / "validation_rule_library.json"
                if rule_path.exists():
                    rules = json.loads(rule_path.read_text())
                    q_lower = query.lower()
                    for dom in target_domains:
                        dom_rules = rules.get(dom) or rules.get(dom.replace("_", " ")) or []
                        for rule in dom_rules[:3]:
                            text = rule if isinstance(rule, str) else str(rule)
                            if any(kw in q_lower for kw in dom.split("_")) or True:
                                chunks.append({"text": text, "domain": dom, "score": 1.0})
            except Exception as exc:
                logger.debug("Rulebook JSON fallback: %s", exc)

        return chunks[:8]

    # ── History / LTM retrieval ────────────────────────────────────────────

    def _fetch_history(
        self,
        query: str,
        db=None,
    ) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        if db is None:
            return chunks
        try:
            from report_builder.memory import ReflectionLedger
            ledger = ReflectionLedger(db)
            chunks = ledger.retrieve_similar("deep_agent", query, limit=5)
        except Exception as exc:
            logger.debug("History retrieval: %s", exc)
        return chunks

    # ── Phase3 / analysis payload retrieval ───────────────────────────────

    def _fetch_phase3(
        self,
        analysis_payload: dict[str, Any],
        target_columns: list[str],
    ) -> tuple[list[dict], list[dict], list[dict]]:
        phase3 = analysis_payload.get("phase3") or {}

        anomalies = [
            c for c in (phase3.get("anomaly_candidates") or [])
            if isinstance(c, dict) and (not target_columns or c.get("column") in target_columns)
        ][:100]

        imputations = [
            c for c in (phase3.get("imputation_candidates") or [])
            if isinstance(c, dict) and (not target_columns or c.get("column") in target_columns)
        ][:50]

        validations = [
            c for c in (phase3.get("validation_candidates") or [])
            if isinstance(c, dict) and (not target_columns or c.get("column") in target_columns)
        ][:50]

        return anomalies, imputations, validations

    # ── Main retrieve ──────────────────────────────────────────────────────

    def retrieve(
        self,
        *,
        analysis_id: int,
        df_loader: Callable[[], pd.DataFrame],
        analysis_payload: dict[str, Any],
        plan,                      # ExecutionPlan from PlannerAgent
        db=None,
    ) -> RetrievalBundle:
        target_columns = list(plan.target_columns or [])
        target_domains = list(plan.target_domains or [])
        query = plan.query

        # 1. Dataset
        df, resolved, domain_map = self._fetch_dataset(
            analysis_id, df_loader, target_columns, target_domains, analysis_payload
        )
        # Update resolved with KG-informed columns
        if not resolved:
            resolved = list(df.columns)[:20]

        # 2. KG
        kg_neighbors, kg_paths = [], []
        if plan.needs_kg:
            kg_neighbors, kg_paths = self._fetch_kg(
                analysis_id, analysis_payload, resolved, target_domains
            )
            # Expand resolved columns from KG
            for n in kg_neighbors:
                col = n.get("column")
                if col and col in (list(df.columns) if not df.empty else []) and col not in resolved:
                    resolved.append(col)

        # 3. Rulebooks
        rulebook_chunks: list[dict] = []
        if plan.needs_rulebook:
            rulebook_chunks = self._fetch_rulebooks(query, target_domains, db)

        # 4. History
        history_chunks: list[dict] = []
        if plan.needs_history:
            history_chunks = self._fetch_history(query, db)

        # 5. Phase3
        anomalies, imputations, validations = self._fetch_phase3(
            analysis_payload, resolved
        )

        return RetrievalBundle(
            df=df,
            kg_neighbors=kg_neighbors,
            kg_paths=kg_paths,
            rulebook_chunks=rulebook_chunks,
            history_chunks=history_chunks,
            anomaly_candidates=anomalies,
            imputation_candidates=imputations,
            validation_candidates=validations,
            resolved_columns=resolved,
            domain_columns=domain_map,
        )
