"""
Context-grounded dynamic statistical domains (cohorts of columns).
Generated deterministically from embeddings — no hand-maintained subdomain lists.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import re
from collections.abc import Callable
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity


def _slug_tokens(names: list[str], max_len: int = 8) -> str:
    raw = "_".join(sorted(names))[:200]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return digest


_VECTOR_GATE_THRESHOLD = 0.75


class DynamicDomainGenerator:
    """
    For each embedding cohort (within provisional parent domain), register a runtime domain
    whose description is anchored on dataset archetype + member column semantics.
    """

    def __init__(self, max_dynamic_domains: int = 24, min_cluster_size: int = 1):
        self.max_dynamic_domains = max_dynamic_domains
        self.min_cluster_size = min_cluster_size

    def generate(
        self,
        dataset_type: str,
        normalized_columns: dict[str, str],
        column_embeddings: dict[str, np.ndarray],
        provisional_domains: dict[str, str],
        schema_graph=None,
        dataset_domain: str | None = None,
        column_phase_1_scores: dict[str, dict[str, float]] | None = None,
        embed_text_fn: Callable[[str], np.ndarray] | None = None,
    ) -> dict[str, dict[str, Any]]:
        columns = list(normalized_columns.keys())
        if not columns:
            return {}

        gemini_anchor_enabled = os.getenv(
            "GEMINI_DYNAMIC_ANCHOR_ENABLED", "true"
        ).strip().lower() not in {"0", "false", "no", "off"}

        generate_semantic_anchor = None
        if gemini_anchor_enabled:
            try:
                anchor_mod = importlib.import_module("services.gemini_dynamic_generator")
                generate_semantic_anchor = getattr(anchor_mod, "generate_semantic_anchor", None)
            except (ImportError, AttributeError):
                pass
        else:
            print("ℹ️ Phase 2 Gemini dynamic anchor disabled (GEMINI_DYNAMIC_ANCHOR_ENABLED=false)")

        embedder_vecs = np.stack([column_embeddings[c] for c in columns])
        n = len(columns)
        k = min(self.max_dynamic_domains, max(1, n // 2 or 1))

        if n == 1:
            labels = np.array([0])
        else:
            # Do not force n_clusters. 0.35 cosine distance ≈ 65% similarity minimum to cluster.
            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=0.35,
                metric="cosine",
                linkage="average",
            )
            labels = clustering.fit_predict(embedder_vecs)

        groups: dict[int, list[str]] = {}
        for col, lab in zip(columns, labels):
            groups.setdefault(int(lab), []).append(col)

        runtime: dict[str, dict[str, Any]] = {}
        sim_mat = cosine_similarity(embedder_vecs)
        col_index = {c: i for i, c in enumerate(columns)}

        for lab, members in groups.items():
            if len(members) < self.min_cluster_size:
                continue
            parent_votes: dict[str, int] = {}
            for m in members:
                p = provisional_domains.get(m, "general")
                parent_votes[p] = parent_votes.get(p, 0) + 1
            parent_mode = max(parent_votes, key=parent_votes.get)

            intra_sims = []
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    intra_sims.append(float(sim_mat[col_index[a]][col_index[b]]))
            cohesion = float(np.mean(intra_sims)) if intra_sims else 1.0

            slug = _slug_tokens(members)
            domain_key = f"dyn_{parent_mode}_{slug}"
            member_labels = [normalized_columns[m] for m in members]

            semantic_title: str | None = None
            anchor_scores: dict[str, float] = {}
            assigned_members = list(members)
            anchor = None
            if generate_semantic_anchor:
                cohort_data = []
                for col in members:
                    raw_scores = (column_phase_1_scores or {}).get(col, {})
                    hints = {
                        k: float(v)
                        for k, v in raw_scores.items()
                        if float(v) > 0.50
                    }
                    cohort_data.append(
                        {"column_name": col, "phase_1_correlations": hints}
                    )
                try:
                    anchor = generate_semantic_anchor(
                        dataset_archetype=dataset_type,
                        cohort_data=cohort_data,
                    )
                except Exception:
                    anchor = None

            if not generate_semantic_anchor or not anchor:
                continue

            semantic_title = str(anchor.get("title", "")).strip() or None
            if not semantic_title:
                continue

            desc = str(anchor.get("description", "")).strip()
            if not desc or not embed_text_fn:
                continue

            # Phase 2: 1-to-5 match — embed each keyword; column passes on max_sim
            keywords = [k.strip() for k in desc.split(",") if k.strip()][:5]
            if not keywords:
                continue
            print(f"\n✨ LLM Generated Domain: '{semantic_title}' | Keywords: {keywords}")
            gated: list[str] = []
            for col in members:
                norm_col_text = normalized_columns[col]
                query_text = (
                    f"Represent this sentence for searching relevant passages: {norm_col_text}"
                )
                col_vec = np.asarray(embed_text_fn(query_text), dtype=np.float64)
                max_sim = -1.0
                print(f"  🔍 TESTING [{col}]:")
                for kw in keywords:
                    kw_vec = np.asarray(embed_text_fn(kw), dtype=np.float64)
                    max_sim = max(max_sim, float(np.dot(col_vec, kw_vec)))
                print(f"      ⭐ MAX SCORE for {col}: {max_sim:.4f} (Threshold is {_VECTOR_GATE_THRESHOLD})")
                if max_sim >= _VECTOR_GATE_THRESHOLD:
                    gated.append(col)
                    anchor_scores[col] = round(max_sim, 4)
                else:
                    print(f"      ❌ REJECTED by Vector Gate")
            # Cohort Quorum Rule: Prevent single noise columns from hijacking the domain
            if len(gated) < max(2, len(members) // 2):
                continue
            assigned_members = gated
            if not assigned_members:
                continue

            tokens = set()
            for lbl in member_labels:
                tokens.update(re.findall(r"[a-z0-9]+", lbl.lower()))
            keywords = sorted(tokens)[:40]

            runtime[domain_key] = {
                "description": desc,
                "keywords": keywords,
                "metadata": {
                    "parent_theme": parent_mode,
                    "members": assigned_members,
                    "cohesion": round(cohesion, 4),
                    "cohort_label": lab,
                    "semantic_title": semantic_title,
                    "anchor_scores": anchor_scores,
                },
            }
        return runtime
