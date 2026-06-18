"""
STEP 6-8 — Domain Matching Engine, LLM Fallback, Domain Confidence.

For every column we compute a weighted match score against the unified domain
registry:

    final = 0.40 * embedding        (column repr vs domain doc, via Qdrant)
          + 0.20 * sample_values    (value tokens overlap domain synonyms/examples)
          + 0.15 * domain_context   (column dtype fits the domain's nature)
          + 0.15 * statistics       (numeric/categorical signal vs domain kind)
          + 0.10 * keyword          (name tokens overlap domain keywords)

If ``final < LLM_FALLBACK_THRESHOLD`` (0.80) the column is escalated to the LLM
(STEP 7), which either picks one of the top-5 candidate domains or proposes a
new grounded domain. The result records ``source`` = 'embedding' | 'llm'
(STEP 8). Columns that stay below ``UNCORRELATED_THRESHOLD`` become
'uncorrelated'.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from semantic_mapping_v2.config import (
    LLM_FALLBACK_THRESHOLD,
    MATCH_WEIGHTS,
    UNCORRELATED_THRESHOLD,
)
from semantic_mapping_v2.domain_loader import Domain
from semantic_mapping_v2.domain_synthesis import UnifiedDomainRegistry
from semantic_mapping_v2.embedder import SemanticEmbedder
from semantic_mapping_v2.feature_extraction import ColumnFeature
from semantic_mapping_v2.llm_client import generate_text, llm_configured, strip_json_fence

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# NOTE: dataset-specific code→domain heuristics (e.g. ASI block codes J11/HI3)
# were removed. Cryptic column codes are now expanded to meaningful English by
# the LLM-primary enricher (column_enricher.enrich_column_features) BEFORE
# matching, so the semantic/embedding match generalises to any dataset instead
# of relying on a hardcoded lookup that only covered one survey family.

# Which dtypes a domain "kind" tends to imply, for the context/statistics signals.
_NUMERIC_HINT_WORDS = {
    "income", "wage", "wages", "salary", "expenditure", "value", "amount", "cost",
    "reserves", "capacity", "generation", "consumption", "production", "yield",
    "index", "inflation", "rate", "metric", "metrics", "quantity", "price",
    "emissions", "population", "mortality", "fertility", "capital", "tariff",
}
_CATEGORICAL_HINT_WORDS = {
    "status", "type", "category", "group", "occupation", "industry", "religion",
    "gender", "sex", "marital", "class", "code", "geography", "state", "district",
    "sector", "crop", "disease", "resource", "unit", "social",
}
_ID_HINT_WORDS = {"identifier", "id", "key", "serial", "code"}


@dataclass
class ColumnMapping:
    column: str
    normalized_name: str
    domain: str
    confidence: float
    source: str  # 'embedding' | 'llm' | 'uncorrelated'
    domain_type: str = "static"
    signals: dict[str, float] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "normalized_name": self.normalized_name,
            "domain": self.domain,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "domain_type": self.domain_type,
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "candidates": self.candidates,
            "explanation": self.explanation,
        }


def _tokens(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        if t:
            out.update(_TOKEN_RE.findall(str(t).lower()))
    return out


class MatchingEngine:
    def __init__(
        self,
        registry: UnifiedDomainRegistry,
        embedder: SemanticEmbedder | None = None,
        *,
        llm_threshold: float = LLM_FALLBACK_THRESHOLD,
    ):
        self.registry = registry
        self.embedder = embedder or registry.embedder
        self.llm_threshold = llm_threshold
        self._domain_by_name = {d.domain_name.lower(): d for d in registry.domains.values()}

    def map_columns(
        self,
        *,
        usecase: str,
        dataset_id: str,
        dataset_name: str,
        features: dict[str, ColumnFeature],
        column_query_vectors: dict[str, np.ndarray],
        use_llm: bool = True,
    ) -> dict[str, ColumnMapping]:
        results: dict[str, ColumnMapping] = {}
        pending: list[str] = []

        # Pass 1 — embedding/weighted scoring for every column.
        for col, feat in features.items():
            qvec = column_query_vectors[col]
            hits = self.registry.search(
                usecase, dataset_id, qvec.tolist(), include_dynamic=True, limit=5
            )
            mapping = self._score_column(feat, hits)
            results[col] = mapping
            if use_llm and mapping.confidence < self.llm_threshold:
                kw = float(mapping.signals.get("keyword", 0))
                # Strong lexical + reasonable composite → keep embedding match (save LLM).
                if kw >= 0.65 and mapping.confidence >= 0.52:
                    mapping.confidence = max(mapping.confidence, 0.72)
                else:
                    pending.append(col)

        # Pass 2 — STEP 7 LLM fallback for low-confidence columns in ONE call.
        if pending:
            llm_maps = self._llm_fallback_batch(
                usecase=usecase,
                dataset_name=dataset_name,
                pending={c: features[c] for c in pending},
                candidates={c: results[c].candidates for c in pending},
            )
            for col, llm_map in llm_maps.items():
                if llm_map is not None:
                    results[col] = llm_map

        # Pass 3 — modest boost for strong lexical + embedding agreement (no LLM).
        for mapping in results.values():
            if mapping.source == "llm":
                continue
            kw = float(mapping.signals.get("keyword", 0))
            emb = float(mapping.signals.get("embedding", 0))
            if kw >= 0.45 and emb >= 0.42:
                mapping.confidence = max(mapping.confidence, 0.48)
            if kw >= 0.55 and emb >= 0.38:
                mapping.confidence = max(mapping.confidence, 0.52)
            if kw >= 0.35 and emb >= 0.48:
                mapping.confidence = max(mapping.confidence, 0.46)

        # Pass 4 — uncorrelated floor (STEP 8).
        for col, mapping in results.items():
            if mapping.confidence < UNCORRELATED_THRESHOLD and mapping.source != "llm":
                mapping.domain = "uncorrelated"
                mapping.source = "uncorrelated"
                mapping.domain_type = "none"
                mapping.explanation = (
                    f"Best match {mapping.signals.get('embedding', 0):.2f} below "
                    f"uncorrelated floor {UNCORRELATED_THRESHOLD}."
                )
        return results

    # -- scoring -------------------------------------------------------------
    def _score_column(
        self, feat: ColumnFeature, hits: list[dict[str, Any]]
    ) -> ColumnMapping:
        candidates: list[dict[str, Any]] = []
        best: tuple[float, dict[str, float], dict[str, Any]] | None = None

        for hit in hits:
            payload = hit["payload"]
            domain_name = str(payload.get("domain_name") or "unknown")
            domain = self._domain_by_name.get(domain_name.lower())

            emb = self._norm_cosine(float(hit["score"]))
            samp = self._sample_signal(feat, domain, payload)
            ctx = self._context_signal(feat, domain_name)
            stat = self._stats_signal(feat, domain_name)
            kw = self._keyword_signal(feat, domain, payload)

            signals = {
                "embedding": emb,
                "sample_values": samp,
                "domain_context": ctx,
                "statistics": stat,
                "keyword": kw,
            }
            final = sum(MATCH_WEIGHTS[k] * signals[k] for k in MATCH_WEIGHTS)
            candidates.append(
                {
                    "domain": domain_name,
                    "domain_type": str(payload.get("domain_type", "static")),
                    "score": round(final, 4),
                    "signals": {k: round(v, 4) for k, v in signals.items()},
                }
            )
            if best is None or final > best[0]:
                best = (final, signals, payload)

        if best is None:
            return ColumnMapping(
                column=feat.name,
                normalized_name=feat.normalized,
                domain="uncorrelated",
                confidence=0.0,
                source="uncorrelated",
                domain_type="none",
                signals={},
                candidates=[],
                explanation="No domain candidates returned from registry.",
            )

        final, signals, payload = best
        domain_name = str(payload.get("domain_name") or "unknown")
        # STEP 8 — margin-aware confidence: a winner that clearly separates from
        # the runner-up is trustworthy; a near-tie stays cautious. Principled
        # calibration (same idea as the usecase detector), not data-specific.
        ordered = sorted((c["score"] for c in candidates), reverse=True)
        runner_up = ordered[1] if len(ordered) > 1 else 0.0
        margin = max(0.0, final - runner_up)
        calibrated = final + min(0.30, 1.2 * margin)
        confidence = round(min(0.99, calibrated), 4)
        return ColumnMapping(
            column=feat.name,
            normalized_name=feat.normalized,
            domain=domain_name,
            confidence=confidence,
            source="embedding",
            domain_type=str(payload.get("domain_type", "static")),
            signals=signals,
            candidates=candidates,
            explanation=(
                f"Matched '{domain_name}' (score {final:.2f}, margin {margin:.2f}): "
                f"emb={signals['embedding']:.2f}, kw={signals['keyword']:.2f}, "
                f"ctx={signals['domain_context']:.2f}."
            ),
        )

    @staticmethod
    def _norm_cosine(score: float) -> float:
        # Qdrant COSINE similarity is in [-1, 1]; map to [0, 1].
        return max(0.0, min(1.0, (score + 1.0) / 2.0)) if score < 0 else min(1.0, score)

    def _sample_signal(
        self, feat: ColumnFeature, domain: Domain | None, payload: dict[str, Any]
    ) -> float:
        value_tokens = _tokens(*[str(v) for v in feat.samples])
        if not value_tokens:
            # No samples — neutral (don't punish header-only metadata).
            return 0.5
        domain_tokens: set[str] = set()
        if domain is not None:
            domain_tokens = domain.keyword_tokens()
        else:
            domain_tokens = _tokens(
                str(payload.get("domain_name", "")),
                *[str(s) for s in payload.get("synonyms", [])],
            )
        if not domain_tokens:
            return 0.3
        overlap = len(value_tokens & domain_tokens)
        return min(1.0, overlap / max(1, min(len(value_tokens), 4)))

    def _context_signal(self, feat: ColumnFeature, domain_name: str) -> float:
        name_tokens = set(_TOKEN_RE.findall(domain_name.lower()))
        dtype = feat.dtype
        if name_tokens & _ID_HINT_WORDS:
            return 1.0 if dtype == "id" else (0.4 if dtype in {"numeric", "categorical"} else 0.2)
        if name_tokens & _NUMERIC_HINT_WORDS:
            return 1.0 if dtype == "numeric" else (0.4 if dtype in {"categorical", "id"} else 0.3)
        if name_tokens & _CATEGORICAL_HINT_WORDS:
            if dtype in {"categorical", "text", "boolean"}:
                return 1.0
            if dtype == "id":
                return 0.6
            return 0.4
        return 0.5  # neutral when the domain kind is ambiguous

    def _stats_signal(self, feat: ColumnFeature, domain_name: str) -> float:
        name_tokens = set(_TOKEN_RE.findall(domain_name.lower()))
        if feat.dtype == "numeric" and feat.statistics:
            # Domains that imply magnitudes reward numeric spread.
            if name_tokens & _NUMERIC_HINT_WORDS:
                std = feat.statistics.get("std", 0.0)
                return 1.0 if std and std > 0 else 0.7
            return 0.5
        if feat.dtype in {"categorical", "boolean"}:
            if name_tokens & _CATEGORICAL_HINT_WORDS:
                return 1.0
            # Low cardinality fits categorical-style domains.
            return 0.6 if feat.cardinality and feat.cardinality <= 30 else 0.4
        if feat.dtype == "id":
            return 1.0 if name_tokens & _ID_HINT_WORDS else 0.3
        return 0.5

    def _keyword_signal(
        self, feat: ColumnFeature, domain: Domain | None, payload: dict[str, Any]
    ) -> float:
        name_tokens = _tokens(feat.name, feat.normalized)
        if not name_tokens:
            return 0.0
        if domain is not None:
            domain_tokens = domain.keyword_tokens()
        else:
            domain_tokens = _tokens(
                str(payload.get("domain_name", "")),
                *[str(s) for s in payload.get("synonyms", [])],
            )
        if not domain_tokens:
            return 0.0
        overlap = len(name_tokens & domain_tokens)
        # Exact name token match is a strong signal.
        return min(1.0, overlap / max(1, min(len(name_tokens), 3)))

    # -- STEP 7: LLM fallback (batched: one call for all low-conf columns) ---
    def _llm_fallback_batch(
        self,
        *,
        usecase: str,
        dataset_name: str,
        pending: dict[str, ColumnFeature],
        candidates: dict[str, list[dict[str, Any]]],
    ) -> dict[str, ColumnMapping | None]:
        out: dict[str, ColumnMapping | None] = {c: None for c in pending}
        if not llm_configured():
            return out

        chunk_size = max(1, int(os.getenv("SEMV2_LLM_BATCH_SIZE", "8")))
        pending_list = list(pending.items())

        chunk_delay = float(os.getenv("SEMV2_LLM_CHUNK_DELAY", "2.5"))
        for start in range(0, len(pending_list), chunk_size):
            if start > 0:
                time.sleep(chunk_delay)
            chunk = pending_list[start : start + chunk_size]
            items = []
            for col, feat in chunk:
                items.append(
                    {
                        "column_name": feat.name,
                        "dtype": feat.dtype,
                        "samples": [str(v)[:20] for v in feat.samples[:3]],
                        "candidate_domains": [c["domain"] for c in candidates.get(col, [])[:4]],
                    }
                )
            prompt = f"""Assign ONE semantic domain per column for '{usecase}' dataset '{dataset_name}'.

COLUMNS:
{json.dumps(items, ensure_ascii=True)}

Rules: prefer candidate_domains; else new snake_case domain; else "uncorrelated".
Return JSON only: {{"columns":[{{"column_name":"...","domain":"...","confidence":0.0}}]}}"""
            try:
                raw = generate_text(
                    prompt,
                    system="Return valid JSON only.",
                )
                data = json.loads(strip_json_fence(raw))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LLM fallback chunk failed (%d cols): %s",
                    len(chunk),
                    exc,
                )
                continue

            if isinstance(data, dict):
                data = data.get("columns") or data.get("results") or [data]
            if not isinstance(data, list):
                continue

            by_name = {
                str(d.get("column_name", "")).strip(): d
                for d in data
                if isinstance(d, dict)
            }
            for col, feat in chunk:
                entry = by_name.get(col) or by_name.get(feat.name)
                if entry is None:
                    continue
                out[col] = self._mapping_from_llm(feat, entry, candidates.get(col, []))
        return out

    @staticmethod
    def _generate_with_retry(model, prompt: str):
        retries = int(os.getenv("GEMINI_LLM_MAX_RETRIES", "3"))
        timeout = int(os.getenv("GEMINI_REQUEST_TIMEOUT_SEC", "60"))
        delay = float(os.getenv("GEMINI_LLM_RETRY_BASE", "8"))
        last: Exception | None = None
        for attempt in range(retries):
            try:
                return model.generate_content(prompt, request_options={"timeout": timeout})
            except Exception as exc:  # noqa: BLE001
                last = exc
                msg = str(exc).lower()
                if not any(k in msg for k in ("429", "quota", "rate", "exhaust", "503")):
                    raise
                if attempt == retries - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
        raise last if last else RuntimeError("unreachable")

    def _mapping_from_llm(
        self, feat: ColumnFeature, data: dict[str, Any], candidates: list[dict[str, Any]]
    ) -> ColumnMapping:
        domain = str(data.get("domain") or "uncorrelated").strip().lower()
        domain = "_".join(_TOKEN_RE.findall(domain)) or "uncorrelated"
        try:
            conf = float(data.get("confidence", 0.8))
        except (TypeError, ValueError):
            conf = 0.8
        source = "uncorrelated" if domain == "uncorrelated" else "llm"
        return ColumnMapping(
            column=feat.name,
            normalized_name=feat.normalized,
            domain=domain,
            confidence=max(0.0, min(1.0, conf)),
            source=source,
            domain_type="dynamic" if source == "llm" else "none",
            signals={},
            candidates=candidates,
            explanation=f"LLM fallback: {str(data.get('reason', '')).strip()}",
        )
