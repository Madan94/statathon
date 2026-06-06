"""
Column normalization for V2 (standalone copy of MoSPI preprocessor logic).

Does not import model.semantic_mapping.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from semantic_mapping_v2.config import MOSPI_DICTIONARY_PATH


class ColumnPreprocessorV2:
    BASE_ABBREVIATIONS = {
        "amt": "amount", "qty": "quantity", "num": "number",
        "yr": "year", "yrs": "years", "mo": "month", "mos": "months",
        "avg": "average", "max": "maximum", "min": "minimum",
        "sal": "salary", "exp": "expenditure", "occ": "occupation",
        "ben": "beneficiary", "pri": "primary", "psu": "primary sampling unit",
        "tot": "total", "pct": "percent", "usd": "us dollars", "inr": "indian rupees",
        "hh": "household", "edu": "education", "emp": "employment",
        "pop": "population", "dist": "district", "govt": "government",
        "med": "medical", "ins": "insurance", "idx": "index", "lvl": "level",
        "grp": "group", "cd": "code", "desc": "description", "flg": "flag",
        "st": "state", "blk": "block",
    }

    def __init__(self):
        self.abbreviations = self.BASE_ABBREVIATIONS.copy()
        if MOSPI_DICTIONARY_PATH.exists():
            try:
                with open(MOSPI_DICTIONARY_PATH, encoding="utf-8") as f:
                    self.abbreviations.update(json.load(f))
            except Exception:
                pass

    def normalize_column(self, column_name: str) -> str:
        text = column_name.replace("_", " ").replace("-", " ")
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s]", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def expand_abbreviations(self, text: str) -> str:
        return " ".join(self.abbreviations.get(t, t) for t in text.split())

    def to_sentence(self, column_name: str) -> str:
        normalized = self.normalize_column(column_name)
        return self.expand_abbreviations(normalized)

    def normalize_columns(self, columns: list[str]) -> dict[str, str]:
        return {col: self.to_sentence(col) for col in columns}
