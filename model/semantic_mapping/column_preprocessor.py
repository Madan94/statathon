import re


class ColumnPreprocessor:

    ABBREVIATIONS = {
        "amt": "amount",
        "qty": "quantity",
        "num": "number",
        "yr": "year",
        "yrs": "years",
        "mo": "month",
        "mos": "months",
        "avg": "average",
        "max": "maximum",
        "min": "minimum",
        "sal": "salary",
        "exp": "expenditure",
        "occ": "occupation",
        "ben": "beneficiary",
        "pri": "primary",
        "psu": "primary sampling unit",
        "tot": "total",
        "pct": "percent",
        "usd": "us dollars",
        "inr": "indian rupees",
        "hh": "household",
        "edu": "education",
        "emp": "employment",
        "pop": "population",
        "dist": "district",
        "govt": "government",
        "med": "medical",
        "ins": "insurance",
        "idx": "index",
        "lvl": "level",
        "grp": "group",
        "cd": "code",
        "desc": "description",
        "flg": "flag",
        "st": "state",
        "blk": "block",
    }

    @staticmethod
    def normalize_column(column_name: str) -> str:
        text = column_name.replace("_", " ").replace("-", " ")
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        text = text.lower().strip()
        text = re.sub(r'[^a-z0-9\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def expand_abbreviations(text: str) -> str:
        tokens = text.split()
        expanded = []
        for token in tokens:
            expanded.append(ColumnPreprocessor.ABBREVIATIONS.get(token, token))
        return " ".join(expanded)

    @staticmethod
    def extract_tokens(column_name: str) -> list:
        normalized = ColumnPreprocessor.normalize_column(column_name)
        expanded = ColumnPreprocessor.expand_abbreviations(normalized)
        tokens = expanded.split()
        return tokens

    @staticmethod
    def to_sentence(column_name: str) -> str:
        tokens = ColumnPreprocessor.extract_tokens(column_name)
        return " ".join(tokens)

    @staticmethod
    def normalize_columns(columns):
        normalized = {}
        for col in columns:
            normalized[col] = ColumnPreprocessor.to_sentence(col)
        return normalized