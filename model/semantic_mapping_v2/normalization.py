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
        # PLFS / HCES / ASI survey-specific
        "fsu": "first stage unit", "fod": "field operations division",
        "nss": "national sample survey", "nssr": "nss region",
        "ssu": "second stage unit", "mult": "multiplier weight",
        "hhld": "household", "hhsize": "household size",
        "mpce": "monthly per capita expenditure",
        "umce": "usual monthly consumption expenditure",
        "nic": "national industrial classification",
        "nco": "national classification occupations",
        "lfpr": "labour force participation rate",
        "wpr": "worker population ratio",
        "ue": "unemployment",
        "wfpr": "worker force participation rate",
        "sc": "scheduled caste", "obc": "other backward class",
        "pds": "public distribution system",
        "val": "value", "wt": "weight", "wgt": "weight",
        "ans": "answer", "rsp": "response",
        "sec": "section", "subsec": "sub section",
        "qno": "question number", "qst": "questionnaire",
        "sch": "schedule", "schid": "schedule identifier",
        "slno": "serial number", "sno": "serial number",
        "srl": "serial", "srno": "serial number",
        "cen": "census", "surv": "survey",
        "rur": "rural", "urb": "urban",
        "agr": "agriculture", "mfg": "manufacturing",
        "ind": "industry", "svc": "service",
        "inc": "income", "wg": "wage", "earn": "earnings",
        "pkg": "package", "pkg_wg": "package wage",
        "ann": "annual", "mon": "monthly", "wkly": "weekly",
        "reg": "regular", "cas": "casual", "contr": "contract",
        "hrd": "hard", "sft": "soft",
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
