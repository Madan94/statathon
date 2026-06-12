"""Load every tabular file under test_data/ for integration tests."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DATA = REPO_ROOT / "test_data"

TABULAR_EXT = {".csv", ".txt", ".tsv", ".xlsx", ".xls"}
SKIP_EXT = {".json", ".pdf", ".json.txt", ".ast.json.txt"}
SKIP_NAME_PARTS = ("fina-ast", "enterprise_document_ast", "general-ast", "ast.json")


def _is_skipped(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in {".json", ".pdf"}:
        return True
    if name.endswith(".json.txt"):
        return True
    for part in SKIP_NAME_PARTS:
        if part in name.replace("-", "_"):
            return True
    return False


def _read_txt(path: Path) -> tuple[pd.DataFrame | None, str]:
    """Try delimiter detection; fixed-width microdata returns None."""
    with open(path, encoding="utf-8", errors="replace") as f:
        sample = f.read(4096)
    if not sample.strip():
        return None, "empty_txt"
    first = sample.splitlines()[0]
    # NSS PLFS / CMSE fixed-width microdata (no delimiters; CFV* record prefix).
    stripped = first.strip()
    if (
        len(stripped) > 180
        and stripped[:4].isalpha()
        and stripped[4:5].isdigit()
        and "," not in stripped
        and "\t" not in stripped
    ):
        return None, "fixed_width_microdata"
    if "," in first:
        return pd.read_csv(path, low_memory=False), "txt_csv"
    if "\t" in first:
        return pd.read_csv(path, sep="\t", low_memory=False), "txt_tsv"
    try:
        return pd.read_csv(path, sep=r"\s+", engine="python", on_bad_lines="skip"), "txt_whitespace"
    except Exception:
        return None, "txt_unparseable"


def load_tabular(path: Path, *, max_rows: int | None = None) -> tuple[pd.DataFrame | None, str]:
    ext = path.suffix.lower()
    if ext == ".csv":
        try:
            df = pd.read_csv(path, low_memory=False)
        except pd.errors.EmptyDataError:
            return None, "empty_csv"
        kind = "csv"
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)
        kind = "excel"
    elif ext == ".txt":
        df, kind = _read_txt(path)
        if df is None:
            return None, kind
    else:
        return None, f"unsupported_{ext}"

    if df is not None and max_rows and len(df) > max_rows:
        df = df.head(max_rows).copy()
    return df, kind


def discover_testdata_files() -> list[Path]:
    if not TEST_DATA.exists():
        return []
    out: list[Path] = []
    for p in sorted(TEST_DATA.rglob("*")):
        if not p.is_file():
            continue
        if _is_skipped(p):
            continue
        ext = p.suffix.lower()
        if ext in TABULAR_EXT or ext == ".txt":
            out.append(p)
    return out


def dedupe_by_content(paths: list[Path]) -> list[Path]:
    """Drop byte-identical duplicates (nested HCES copies)."""
    seen: dict[str, Path] = {}
    unique: list[Path] = []
    for p in paths:
        try:
            digest = hashlib.md5(p.read_bytes()).hexdigest()
        except OSError:
            continue
        if digest in seen:
            continue
        seen[digest] = p
        unique.append(p)
    return unique


def expected_usecase(path: Path, columns: list[str]) -> str | None:
    p = str(path).lower().replace("\\", "/")
    cols = " ".join(str(c) for c in columns).lower()
    if "unified_energy" in p or "energy" in p and "reserves" in cols:
        return "energy"
    if "economics" in p or "index_al" in cols or "inflation_al" in cols:
        return "industry"
    if "cmse" in p or "plfs" in p or "mospi dataset example" in p:
        return "labour"
    if "c457a87f" in p or ("household_id" in cols and "monthly_wage" in cols):
        return "labour"
    if "hces" in p or "level -" in p or "expenditure" in cols:
        return "consumption"
    if "household" in cols and "expenditure" in cols:
        return "consumption"
    if "asi" in p or "blk" in p and "202324" in p:
        return "industry"
    if "mospi_mock_survey" in p:
        return "consumption"
    if "rapidfuzz" in p:
        return None
    return None
