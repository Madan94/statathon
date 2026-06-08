"""P2 gate tests: entity hygiene (D1) — blocklist/regex classifier + quarantine reasons."""
from __future__ import annotations

from report_builder.extraction_pipeline import _classify_entity_name, _is_valid_entity_name

# Real statistical entities — MUST pass (reason is None).
VALID = [
    "Worker Population Ratio",
    "Labour Force Participation Rate",
    "Unemployment Rate",
    "Gender",
    "Rural",
    "State/UT",
    "Monthly Per Capita Expenditure",
]

# Known D1 leaks — MUST be rejected (reason is a non-None string).
NOISE = [
    "Press Re",
    ":49 AM",
    "10:49 AM",
    "https://pib.gov.in",
    "www.mospi.gov.in",
    "Press Release",
    "Visitor Counter",
    "click here",
    "Posted On",
    "2. ",
    "45.6%",
]


def test_valid_entities_pass():
    for name in VALID:
        assert _classify_entity_name(name) is None, f"{name!r} wrongly rejected"
        assert _is_valid_entity_name(name) is True


def test_noise_entities_rejected_with_reason():
    for name in NOISE:
        reason = _classify_entity_name(name)
        assert reason is not None, f"{name!r} should have been rejected"
        assert isinstance(reason, str) and reason
        assert _is_valid_entity_name(name) is False


def test_specific_reasons():
    assert _classify_entity_name(":49 AM") in ("leading_punct", "time_fragment")
    assert _classify_entity_name("https://pib.gov.in") in ("url", "blocklist_substr")
    assert _classify_entity_name("Press Release") == "blocklist_phrase"
    assert _classify_entity_name("45.6%") in ("embedded_percent", "numeric_only", "starts_with_digit", "no_alpha")


def test_wrapper_consistency():
    # The boolean wrapper must agree with the classifier for every sample.
    for name in VALID + NOISE:
        assert _is_valid_entity_name(name) == (_classify_entity_name(name) is None)
