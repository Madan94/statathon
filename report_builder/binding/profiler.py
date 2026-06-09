"""S0 — Dataset profiler.

Turns a pandas ``DataFrame`` into a :class:`DatasetAST`: per-column dtype, role
(dimension / measure / time / id / metadata), cardinality, sample values, unit,
min/max and null%, plus **wide column-group** detection (members-as-columns /
period-as-columns) with a lazy reshape recipe.

Deterministic, offline, explainable — no LLM, no network. Pandas *is* the
low-level math; role/unit/archetype/group rules are layered on top.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

import pandas as pd

from report_builder.binding.schema import (
    ColumnGroup,
    ColumnProfile,
    DatasetAST,
    ReshapeRecipe,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Role-inference signals (name regexes, applied to a normalized column name)
# ─────────────────────────────────────────────────────────────────────────────

_ID_RE = re.compile(r"(?:^|_)(?:id|code|no|number|uuid|guid|sno|slno|serial)$", re.I)
_TIME_RE = re.compile(
    r"(?:^|_)(?:year|date|datetime|period|round|month|quarter|qtr|fy|fiscal[_ ]?year|yyyy)(?:$|_)",
    re.I,
)
_METADATA_RE = re.compile(
    r"(?:^|_)(?:unit|units|unit[_ ]?of[_ ]?measure|uom|source|sources|footnote|"
    r"footnotes|note|notes|remark|remarks|provenance|currency)(?:$|_)",
    re.I,
)

# Unit parsing from a column name (first match wins).
_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:^|[_\s(])(mw)(?:[)\s_]|$)", re.I), "MW"),
    (re.compile(r"(?:^|[_\s(])(gw)(?:[)\s_]|$)", re.I), "GW"),
    (re.compile(r"(?:percent|_pct|\bpct\b|%|_rate$|ratio)", re.I), "percent"),
    (re.compile(r"(?:₹|\binr\b|rupees?|\brs\b)", re.I), "INR"),
    (re.compile(r"billion\s*tonnes|\bbt\b", re.I), "Billion Tonnes"),
    (re.compile(r"million\s*tonnes|\bmt\b", re.I), "Million Tonnes"),
    (re.compile(r"\btonnes?\b", re.I), "Tonnes"),
    (re.compile(r"\bkwh\b", re.I), "kWh"),
    (re.compile(r"(?:^|_)(?:years?|age)(?:$|_)", re.I), "years"),
]

# Archetype detection — token overlap against column names.
_ARCHETYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "energy": ("reserve", "reserves", "proved", "indicated", "inferred", "potential",
               "capacity", "mw", "tonnes", "coal", "lignite", "petroleum", "renewable"),
    "labour_force": ("lfpr", "wpr", "unemploy", "labour", "labor", "employment",
                     "worker", "participation", "usual_status", "workforce"),
    "consumption": ("mpce", "consumption", "expenditure", "spending", "outlay"),
    "prices": ("cpi", "wpi", "inflation", "index", "price"),
}

# Period token detector (for periodGroup member labels).
_PERIOD_RE = re.compile(r"^(?:(?:19|20)\d{2}(?:[-_]\d{2,4})?|fy\d{2,4}|q[1-4])$", re.I)

_TOKEN_SPLIT_RE = re.compile(r"[_\s\-]+|(?<=[a-z])(?=[A-Z])")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _norm(name: str) -> str:
    return str(name).strip().lower()


def _tokens(name: str) -> list[str]:
    parts = _TOKEN_SPLIT_RE.split(str(name).strip())
    return [p for p in parts if p]


def _singularize(word: str) -> str:
    w = str(word)
    if len(w) > 3 and w.lower().endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.lower().endswith("s") and not w.lower().endswith("ss"):
        return w[:-1]
    return w


def _dtype_of(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_integer_dtype(series):
        return "int"
    if pd.api.types.is_float_dtype(series):
        return "float"
    # object columns that fully parse as dates → date
    return "string"


def _parse_unit(column_name: str) -> str | None:
    for pat, unit in _UNIT_PATTERNS:
        if pat.search(column_name):
            return unit
    return None


def _infer_role(name: str, dtype: str, cardinality: int, unique_ratio: float, nrows: int) -> str:
    """Deterministic role inference (order matters)."""
    norm = _norm(name)
    # 1. metadata — describes other columns (units/source/footnote)
    if _METADATA_RE.search(norm):
        return "metadata"
    # 2. id — name looks like an identifier AND is near-unique
    if _ID_RE.search(norm) and (unique_ratio >= 0.9 or cardinality >= max(nrows - 1, 1)):
        return "id"
    # 3. time — name looks temporal OR dtype is a date
    if dtype == "date" or _TIME_RE.search(norm):
        return "time"
    # 4. measure — numeric and not id/time/metadata
    if dtype in ("int", "float"):
        # A near-unique integer with an id-ish name was caught above; otherwise numeric = measure
        return "measure"
    # 5. dimension — everything else (categorical/text)
    return "dimension"


def _detect_archetype(column_names: list[str]) -> str:
    blob = " ".join(_norm(c).replace("_", " ") for c in column_names)
    best, best_hits = "generic", 0
    for arch, kws in _ARCHETYPE_KEYWORDS.items():
        hits = sum(1 for kw in kws if kw in blob)
        if hits > best_hits:
            best, best_hits = arch, hits
    return best if best_hits >= 2 else "generic"


def _sample_values(series: pd.Series, k: int = 5) -> list[Any]:
    out: list[Any] = []
    for v in series.dropna().unique()[:k]:
        if isinstance(v, (int, float, bool, str)):
            out.append(v.item() if hasattr(v, "item") else v)
        else:
            out.append(str(v))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Wide column-group detection
# ─────────────────────────────────────────────────────────────────────────────


def _detect_groups(profiles: list[ColumnProfile]) -> tuple[list[ColumnGroup], list[ReshapeRecipe]]:
    """Detect measure/period column-groups that share a stem.

    measureGroup: numeric columns sharing the SAME trailing token, differing by
                  the leading token (Proved_Reserves / Indicated_Reserves / …).
    periodGroup:  numeric columns sharing the SAME leading token, differing by a
                  period-like trailing token (WPR_2023_24 / WPR_2024_25).
    """
    numeric = [p for p in profiles if p.role == "measure"]
    groups: list[ColumnGroup] = []
    grouped_cols: set[str] = set()

    # --- measureGroup by shared trailing token ---
    # A true members-as-columns group has PARALLEL structure: every member's
    # leading (member-label) part has the SAME small token-count, e.g.
    # Proved_Reserves / Indicated_Reserves / Total_Reserves (prefix = 1 token).
    # This rejects coincidental suffix collisions such as
    # Labour_Force_Participation_Rate (prefix 3) vs Unemployment_Rate (prefix 1).
    by_suffix: dict[str, list[ColumnProfile]] = {}
    for p in numeric:
        toks = _tokens(p.name)
        if len(toks) >= 2:
            by_suffix.setdefault(toks[-1].lower(), []).append(p)
    for suffix, members in by_suffix.items():
        if len(members) < 2 or _PERIOD_RE.match(suffix):
            continue
        prefixed = [(m, _tokens(m.name)[:-1]) for m in members]
        len_counts = Counter(len(pfx) for _, pfx in prefixed)
        modal_len, _ = len_counts.most_common(1)[0]
        if modal_len == 0 or modal_len > 2:  # member labels are short (1-2 tokens)
            continue
        parallel = [m for m, pfx in prefixed if len(pfx) == modal_len]
        if len(parallel) < 2:
            continue
        leads = {tuple(_tokens(m.name)[:-1]) for m in parallel}
        if len(leads) < 2:  # leading member labels must actually differ
            continue
        groups.append(ColumnGroup(
            stem=_singularize(parallel[0].name.rsplit("_", 1)[-1] if "_" in parallel[0].name else suffix),
            kind="measureGroup",
            members=[m.name for m in parallel],
        ))
        grouped_cols.update(m.name for m in parallel)

    # --- periodGroup by shared leading token ---
    by_prefix: dict[str, list[ColumnProfile]] = {}
    for p in numeric:
        if p.name in grouped_cols:
            continue
        toks = _tokens(p.name)
        if len(toks) >= 2 and _PERIOD_RE.match("_".join(toks[1:])):
            by_prefix.setdefault(toks[0].lower(), []).append(p)
    for prefix, members in by_prefix.items():
        if len(members) < 2:
            continue
        groups.append(ColumnGroup(stem=prefix, kind="periodGroup",
                                  members=[m.name for m in members]))
        grouped_cols.update(m.name for m in members)

    # --- reshape recipes (id vars = everything not in this group) ---
    all_names = [p.name for p in profiles]
    reshapes: list[ReshapeRecipe] = []
    for g in groups:
        id_vars = [n for n in all_names if n not in set(g.members)]
        if g.kind == "measureGroup":
            member_var = f"{_singularize(g.stem)}_type" if g.stem else "member"
        else:
            member_var = "period"
        reshapes.append(ReshapeRecipe(
            groupStem=g.stem, kind="melt", idVars=id_vars,
            valueVar="value", memberVar=member_var,
        ))
    return groups, reshapes


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def profile_dataframe(
    df: pd.DataFrame,
    *,
    dataset_id: str = "",
    source_file: str = "",
) -> DatasetAST:
    """Profile a DataFrame into a :class:`DatasetAST` (S0)."""
    nrows = int(len(df))
    profiles: list[ColumnProfile] = []

    for col in df.columns:
        series = df[col]
        dtype = _dtype_of(series)
        nn = int(series.notna().sum())
        cardinality = int(series.dropna().nunique()) if nn else 0
        unique_ratio = float(cardinality / nn) if nn else 0.0
        null_pct = round(1.0 - (nn / nrows), 6) if nrows else 1.0
        role = _infer_role(str(col), dtype, cardinality, unique_ratio, nrows)
        unit = _parse_unit(str(col))

        prof = ColumnProfile(
            name=str(col),
            dtype=dtype,
            role=role,
            cardinality=cardinality,
            sampleValues=_sample_values(series),
            unit=unit,
            nullPct=null_pct,
        )
        if role == "measure" and dtype in ("int", "float"):
            num = pd.to_numeric(series, errors="coerce").dropna()
            if len(num):
                prof.minValue = float(num.min())
                prof.maxValue = float(num.max())
        profiles.append(prof)

    groups, reshapes = _detect_groups(profiles)
    archetype = _detect_archetype([p.name for p in profiles])

    logger.info(
        "[profiler] %s: %d cols (%d measure, %d dim, %d time, %d id), %d group(s), archetype=%s",
        dataset_id or source_file or "dataset", len(profiles),
        sum(1 for p in profiles if p.role == "measure"),
        sum(1 for p in profiles if p.role == "dimension"),
        sum(1 for p in profiles if p.role == "time"),
        sum(1 for p in profiles if p.role == "id"),
        len(groups), archetype,
    )

    return DatasetAST(
        datasetId=dataset_id or source_file or "dataset",
        sourceFile=source_file,
        rowCount=nrows,
        archetype=archetype,
        columns=profiles,
        columnGroups=groups,
        reshape=reshapes,
    )


def profile_csv(path: str, *, dataset_id: str = "") -> DatasetAST:
    """Convenience: load a CSV and profile it."""
    import os

    df = pd.read_csv(path)
    return profile_dataframe(
        df,
        dataset_id=dataset_id or os.path.splitext(os.path.basename(path))[0],
        source_file=os.path.basename(path),
    )
