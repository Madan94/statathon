"""Offline-mode regression tests (no API key / no LLM / no LayoutLM).

Covers the air-gapped switch and the question-label hygiene that keeps the
deterministic offline path from emitting placeholder or blob entity references.
"""
from __future__ import annotations

import report_builder.llm_router as router
from report_builder.extraction_pipeline import (
    _is_clean_qlabel,
    _is_placeholder_colname,
)
from report_builder.llm_router import (
    is_provider_available,
    llm_disabled,
    llm_text_call,
    llm_vision_call,
)


# ── LLM_DISABLED air-gapped switch ──────────────────────────────────────────
def test_llm_disabled_default_off(monkeypatch):
    monkeypatch.delenv("LLM_DISABLED", raising=False)
    assert llm_disabled() is False


def test_llm_disabled_truthy_values(monkeypatch):
    for val in ("1", "true", "yes", "on", "ON", "True"):
        monkeypatch.setenv("LLM_DISABLED", val)
        assert llm_disabled() is True


def test_disabled_skips_text_and_vision_calls(monkeypatch):
    monkeypatch.setenv("LLM_DISABLED", "1")

    # Even if a backend were reachable, the call must short-circuit to None.
    def _boom(*a, **k):
        raise AssertionError("backend must not be called when LLM_DISABLED=1")

    monkeypatch.setattr(router, "_call_qwen_text", _boom)
    monkeypatch.setattr(router, "_call_qwen_vision", _boom)
    assert llm_text_call("hello", task="reasoning") is None
    assert llm_vision_call("hello", task="entity_extraction") is None


def test_disabled_marks_all_providers_unavailable(monkeypatch):
    monkeypatch.setenv("LLM_DISABLED", "1")
    for prov in ("qwen", "gemini", "groq", "openai"):
        assert is_provider_available(prov) is False
        assert is_provider_available(prov, vision=True) is False


# ── Placeholder column-name detection ───────────────────────────────────────
def test_placeholder_colnames_detected():
    for name in ("col_0", "col_12", "column_3", "Column 4", "unnamed", "field_7", "c_2", ""):
        assert _is_placeholder_colname(name) is True


def test_real_labels_not_placeholders():
    for name in ("States/ UTs", "Coal Reserves", "LFPR", "Gender", "Proved"):
        assert _is_placeholder_colname(name) is False


# ── Clean question-label gate (placeholder + D1 hygiene) ────────────────────
def test_clean_qlabel_accepts_real_labels():
    for name in ("States/ UTs", "Coal Reserves", "Worker Population Ratio", "Gender"):
        assert _is_clean_qlabel(name) is True


def test_clean_qlabel_rejects_placeholders_and_blobs():
    # placeholders
    assert _is_clean_qlabel("col_1") is False
    assert _is_clean_qlabel("") is False
    # blob: multi-line whole-page text (>80 chars) must be rejected
    blob = (
        "Table 1.1: Statewise Estimated Reserves of Coal (As on 1st April 2025)\n"
        "(in Million Tonnes) States/ UTs"
    )
    assert _is_clean_qlabel(blob) is False
