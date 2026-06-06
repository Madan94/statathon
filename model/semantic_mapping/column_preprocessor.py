import re
import json
from pathlib import Path

class ColumnPreprocessor:

    # Fallback/Base dictionary
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
        # 1. Start with base abbreviations
        self.abbreviations = self.BASE_ABBREVIATIONS.copy()
        import os
        
        # Try multiple common path locations to ensure it is found
        possible_paths = [
            Path(__file__).resolve().parents[2] / "model" / "config" / "mospi_dictionary.json",
            Path(os.getcwd()) / "model" / "config" / "mospi_dictionary.json",
            Path(os.getcwd()) / "config" / "mospi_dictionary.json"
        ]
        
        loaded = False
        for dict_path in possible_paths:
            if dict_path.exists():
                try:
                    with open(dict_path, 'r', encoding='utf-8') as f:
                        mospi_dict = json.load(f)
                        self.abbreviations.update(mospi_dict)
                        print(f"✅ SUCCESSFULLY loaded mospi_dictionary.json from {dict_path}")
                        loaded = True
                        break # Stop looking once we found it
                except Exception as e:
                    print(f"⚠️ Failed to parse JSON at {dict_path}: {e}")
                    
        if not loaded:
            print("❌ WARNING: Could not locate mospi_dictionary.json in any expected location.")

    def normalize_column(self, column_name: str) -> str:
        text = column_name.replace("_", " ").replace("-", " ")
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        text = text.lower().strip()
        text = re.sub(r'[^a-z0-9\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def expand_abbreviations(self, text: str) -> str:
        tokens = text.split()
        expanded = []
        for token in tokens:
            expanded.append(self.abbreviations.get(token, token))
        return " ".join(expanded)

    def extract_tokens(self, column_name: str) -> list:
        normalized = self.normalize_column(column_name)
        expanded = self.expand_abbreviations(normalized)
        tokens = expanded.split()
        return tokens

    def to_sentence(self, column_name: str) -> str:
        tokens = self.extract_tokens(column_name)
        return " ".join(tokens)

    def normalize_columns(self, columns):
        normalized = {}
        for col in columns:
            normalized[col] = self.to_sentence(col)
        return normalized