"""P6 tests: max-Qwen hardening — guided_json (Q20) + confidence-gated self-consistency (Q21)."""
from __future__ import annotations

import report_builder.llm_router as router
from report_builder.llm_router import (
    _apply_guided_json,
    _confidence_threshold,
    guided_json_enabled,
    llm_consistent_call,
    self_consistency_enabled,
)
from report_builder.llm_schemas import (
    ENTITY_BINDING_SCHEMA,
    ENTITY_CLASSIFICATION_SCHEMA,
    QUESTION_LIST_SCHEMA,
)
from report_builder.question_quality import QUESTION_TYPES

_SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}}


# ── Q20: guided_json gating + payload application ───────────────────────────
def test_guided_json_enabled_default_on(monkeypatch):
    monkeypatch.delenv("GUIDED_JSON", raising=False)
    assert guided_json_enabled() is True


def test_guided_json_disabled(monkeypatch):
    for val in ("0", "false", "no", "off"):
        monkeypatch.setenv("GUIDED_JSON", val)
        assert guided_json_enabled() is False


def test_apply_guided_json_attaches_when_enabled(monkeypatch):
    monkeypatch.setenv("GUIDED_JSON", "1")
    payload: dict = {"model": "m", "messages": []}
    _apply_guided_json(payload, _SCHEMA)
    assert payload["guided_json"] == _SCHEMA
    assert "guided_decoding_backend" in payload


def test_apply_guided_json_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("GUIDED_JSON", "0")
    payload: dict = {"model": "m"}
    _apply_guided_json(payload, _SCHEMA)
    assert "guided_json" not in payload


def test_apply_guided_json_noop_when_no_schema(monkeypatch):
    monkeypatch.setenv("GUIDED_JSON", "1")
    payload: dict = {"model": "m"}
    _apply_guided_json(payload, None)
    assert "guided_json" not in payload


# ── Q21: self-consistency gating ────────────────────────────────────────────
def test_self_consistency_default_on(monkeypatch):
    monkeypatch.delenv("SELF_CONSISTENCY", raising=False)
    assert self_consistency_enabled() is True


def test_self_consistency_disabled(monkeypatch):
    monkeypatch.setenv("SELF_CONSISTENCY", "off")
    assert self_consistency_enabled() is False


def test_confidence_threshold_parsing(monkeypatch):
    monkeypatch.setenv("SELF_CONSISTENCY_THRESHOLD", "0.8")
    assert _confidence_threshold() == 0.8
    monkeypatch.setenv("SELF_CONSISTENCY_THRESHOLD", "garbage")
    assert _confidence_threshold(0.6) == 0.6


# ── Q21: llm_consistent_call behaviour ──────────────────────────────────────
def _parse(raw: str):
    # raw is "value:confidence"
    value, conf = raw.split(":")
    return value, float(conf)


def test_consistent_high_confidence_single_pass(monkeypatch):
    monkeypatch.setenv("SELF_CONSISTENCY", "1")
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        return "alpha:0.95"

    monkeypatch.setattr(router, "llm_vision_call", fake)
    value, meta = llm_consistent_call("p", _parse, threshold=0.6)
    assert value == "alpha"
    assert meta["passes"] == 1
    assert meta["resampled"] is False
    assert calls["n"] == 1


def test_consistent_low_confidence_resamples_and_picks_best(monkeypatch):
    monkeypatch.setenv("SELF_CONSISTENCY", "1")
    seq = iter(["alpha:0.30", "beta:0.80"])

    monkeypatch.setattr(router, "llm_vision_call", lambda *a, **k: next(seq))
    value, meta = llm_consistent_call("p", _parse, threshold=0.6)
    assert value == "beta"
    assert meta["passes"] == 2
    assert meta["resampled"] is True
    assert meta["confidence"] == 0.80


def test_consistent_disabled_no_resample(monkeypatch):
    monkeypatch.setenv("SELF_CONSISTENCY", "0")
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        return "alpha:0.10"

    monkeypatch.setattr(router, "llm_vision_call", fake)
    value, meta = llm_consistent_call("p", _parse, threshold=0.6)
    assert value == "alpha"
    assert calls["n"] == 1
    assert meta["resampled"] is False


def test_consistent_all_parse_fail_returns_none(monkeypatch):
    monkeypatch.setenv("SELF_CONSISTENCY", "1")
    monkeypatch.setattr(router, "llm_vision_call", lambda *a, **k: None)
    value, meta = llm_consistent_call("p", _parse, threshold=0.6)
    assert value is None
    assert meta["passes"] == 2


def test_consistent_parser_exception_is_safe(monkeypatch):
    monkeypatch.setenv("SELF_CONSISTENCY", "1")
    monkeypatch.setattr(router, "llm_vision_call", lambda *a, **k: "no-colon-here")
    value, meta = llm_consistent_call("p", _parse, threshold=0.6)
    assert value is None  # parser raised → treated as failure, never crashes


# ── Q20: schema sanity ──────────────────────────────────────────────────────
def test_question_schema_enum_matches_canonical_types():
    enum = QUESTION_LIST_SCHEMA["items"]["properties"]["questionType"]["enum"]
    assert set(enum) == set(QUESTION_TYPES)


def test_classification_schema_enum():
    enum = ENTITY_CLASSIFICATION_SCHEMA["items"]["properties"]["type"]["enum"]
    assert set(enum) == {"dimension", "measure", "filter", "metadata"}


def test_binding_schema_has_required_entities():
    props = ENTITY_BINDING_SCHEMA["properties"]
    assert "requiredEntities" in props
    assert "answerStructure" in props
