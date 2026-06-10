"""Generation profiles — policy knobs the formula executor reads (never hardcodes).

MoSPI conventions live here as a **named profile**, not as scattered constants in
the math. Swapping the profile (e.g. a different statistical agency, or a stricter
audit run) changes behaviour without touching `formula_exec`. Everything the
executor needs to make a *policy* decision — how to reconcile differing reported
values, what a zero denominator means, how many digits to round to, the default
multiplier for each formula family — is a field here.

Profiles are deterministic and offline (no env model lookups): they only encode
arithmetic/statistical policy, so `LLM_DISABLED=1` runs are unaffected.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Default multiplier per formula family when the FormulaSpec does not set one
# explicitly (spec.multiplier == 1.0, the dataclass default). SHARE → percent,
# RATE → per-1000, RATIO → bare quotient, INDEX/GROWTH/CAGR → percent.
_DEFAULT_MULTIPLIERS: dict[str, float] = {
    "SHARE": 100.0,
    "RATE": 1000.0,
    "RATIO": 1.0,
    "INDEX": 100.0,
    "GROWTH": 100.0,
    "CAGR": 100.0,
    "DIFFERENCE": 1.0,
    "DIRECT": 1.0,
}


@dataclass(frozen=True)
class GenerationConfig:
    """A named, deterministic policy profile for the generation/formula phase."""

    profile: str = "default"
    # How to collapse a group whose pre-aggregated rate column has DIFFERING values.
    #   "strict"        → leave ambiguous (value None), mark DEGRADED
    #   "weighted_mean" → reconcile by weighted mean iff a valid weight column exists
    reported_value_policy: str = "strict"
    # What a zero denominator means for SHARE/RATE/RATIO.
    #   "null"  → that group's value is None + a diagnostic (never crash, never inf)
    #   "error" → mark the whole result errored
    zero_denominator_policy: str = "null"
    rounding: int = 1                       # decimal places for derived values
    verifier_tolerance: float = 0.05        # ±5% numeric tolerance for the verifier
    multipliers: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_MULTIPLIERS))

    def multiplier_for(self, ftype: str, spec_multiplier: float) -> float:
        """Resolve the multiplier: an explicit non-unit spec value wins, else profile default."""
        if spec_multiplier and spec_multiplier != 1.0:
            return float(spec_multiplier)
        return self.multipliers.get((ftype or "").upper(), 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Profile registry
# ─────────────────────────────────────────────────────────────────────────────

_PROFILES: dict[str, GenerationConfig] = {
    "default": GenerationConfig(profile="default"),
    # MoSPI gold runs reconcile differing officer-reported rates by population weight.
    "mospi": GenerationConfig(
        profile="mospi",
        reported_value_policy="weighted_mean",
        zero_denominator_policy="null",
        rounding=1,
        verifier_tolerance=0.05,
    ),
}


def register_profile(config: GenerationConfig) -> None:
    """Register (or override) a named profile — keeps profiles dynamic, not hardcoded."""
    _PROFILES[config.profile] = config


def load_profile(name: str | None = "default") -> GenerationConfig:
    """Return a named profile, falling back to ``default`` for unknown names."""
    return _PROFILES.get((name or "default"), _PROFILES["default"])


def available_profiles() -> list[str]:
    return sorted(_PROFILES)
