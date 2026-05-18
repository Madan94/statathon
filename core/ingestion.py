import os
import hashlib
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")


settings = Settings()
engine = create_engine(settings.DATABASE_URL)

upload_dir = os.path.join(os.getcwd(), 'data', 'raw_uploads')
os.makedirs(upload_dir, exist_ok=True)


def load_file(path: str) -> pd.DataFrame:
    """Load CSV or Excel for `pipelines.orchestrator`."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    raise ValueError(f"Unsupported file type: {ext}")


def infer_schema(df: pd.DataFrame) -> dict[str, str]:
    """Simple column typing for normalization / outlier rules."""
    schema = {}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            schema[c] = "numeric"
        else:
            num = pd.to_numeric(s, errors="coerce")
            if num.notna().sum() > 0.9 * len(df) or num.notna().sum() >= max(3, len(df) // 2):
                schema[c] = "numeric"
            else:
                schema[c] = "string"
    return schema


def health_summary(df: pd.DataFrame) -> dict:
    missing = df.isna().sum()
    return {
        "rows": int(len(df)),
        "columns": len(df.columns),
        "missing_per_column": {str(k): int(v) for k, v in missing.items()},
        "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
    }


async def load_raw_data(f_stream, original_filename: str):
    session_id = f'sess_{uuid.uuid4().hex[:8]}'
    safe_filename = f'{session_id}_{original_filename}'
    file_path = os.path.join(upload_dir, safe_filename)

    sha256 = hashlib.sha256()

    with open(file_path, 'wb') as buffer:
        while chunk := await f_stream.read(8192):
            buffer.write(chunk)
            sha256.update(chunk)
    
    genesis_hash = sha256.hexdigest()

    df = pd.read_csv(file_path, dtype=str)
    
    dynamic_table_name = f'survey_raw_{session_id}'

    df.to_sql(
        name=dynamic_table_name,
        con=engine,
        if_exists='replace',
        index=False,
        chunksize=10000
    )

    raw_cols = df.columns.tolist()
    tot_rows = len(df)

    schema_map = run_schema_mapping(raw_cols, df)

    return {
        'session_id': session_id,
        'genesis_hash': genesis_hash,
        'dynamic_table_name': dynamic_table_name,
        'total_rows': tot_rows,
        'file_path': file_path,
        'raw_columns': raw_cols
    }

def run_schema_mapping(raw_cols: list, df: pd.DataFrame) -> dict:
    return {}