"""Bind coordinate-AST body paragraphs via coordinate Deep BI execute + prose."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .prose_from_bi import prose_for_query
from .schema import MultiAST

logger = logging.getLogger(__name__)


@dataclass
class ContentBindReport:
    paragraphs_attempted: int = 0
    paragraphs_bound: int = 0
    paragraphs_from_gemini: int = 0
    paragraphs_from_deep_bi: int = 0
    warnings: list[str] = field(default_factory=list)


def _gemini_model():
    try:
        from core.gemini_client import get_generative_model
    except Exception:
        return None
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        return None
    try:
        return get_generative_model()
    except Exception as exc:
        logger.warning("Gemini init failed: %s", exc)
        return None


def _retry_delay_from_error(exc: Exception) -> float:
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), re.I)
    if m:
        return min(float(m.group(1)) + 1.0, 65.0)
    return 8.0


def _gemini_prose(query: str, analytics_payload: dict[str, Any]) -> str | None:
    model = _gemini_model()
    if model is None:
        return None
    prompt = (
        "Write one official MoSPI statistical report paragraph (90–120 words). "
        "Use ONLY the analytics JSON below. Do NOT mention filters, row counts, "
        "debug steps, or column names like 'filtered rows'. Write flowing prose.\n\n"
        f"QUESTION: {query}\n\nANALYTICS:\n{json.dumps(analytics_payload, default=str)[:4000]}"
    )
    for attempt in range(3):
        try:
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            if text and "filtered rows" not in text.lower():
                return text
        except Exception as exc:
            if "429" in str(exc) and attempt < 2:
                time.sleep(_retry_delay_from_error(exc))
                continue
            logger.warning("Gemini prose failed: %s", exc)
    return None


class CoordContentBinder:
    def __init__(self, *, use_gemini: bool = True, strict: bool = False) -> None:
        self._use_gemini = use_gemini
        self._strict = strict

    def bind(
        self,
        ast: MultiAST,
        df: pd.DataFrame,
        facts: dict[str, Any] | None = None,
    ) -> tuple[MultiAST, ContentBindReport]:
        report = ContentBindReport()
        _ = facts
        if df.empty:
            report.warnings.append("empty dataset — skipping content bind")
            return ast, report

        gemini_fn = _gemini_prose if self._use_gemini else None

        for para in ast.contentAST.paragraphs:
            if para.type != "body" or not para.biQuery:
                continue
            report.paragraphs_attempted += 1
            try:
                gemini_used = False
                if gemini_fn:
                    def narrate(q: str, payload: dict) -> str:
                        nonlocal gemini_used
                        out = gemini_fn(q, payload) or ""
                        if out:
                            gemini_used = True
                        return out

                    text = prose_for_query(
                        para.biQuery, df, gemini_narrate=narrate,
                    )
                else:
                    text = prose_for_query(para.biQuery, df)

                if not text or "filtered rows" in text.lower():
                    gemini_used = False
                    text = prose_for_query(para.biQuery, df, gemini_narrate=None)

                if text.strip() and "filtered rows" not in text.lower():
                    words = text.split()
                    if len(words) > 150:
                        text = " ".join(words[:150]).rstrip(",;") + "."
                    para.content = text
                    para.evidenceRefs = [
                        "deep_bi_gemini" if gemini_used else "deep_bi_prose"
                    ]
                    if gemini_used:
                        report.paragraphs_from_gemini += 1
                    else:
                        report.paragraphs_from_deep_bi += 1
                    report.paragraphs_bound += 1
                else:
                    report.warnings.append(f"no prose for {para.id}")
                    if self._strict:
                        para.content = ""
            except Exception as exc:
                report.warnings.append(f"{para.id}: {exc}")

        return ast, report
