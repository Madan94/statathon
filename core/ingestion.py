import io
import os
import hashlib
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pipelines.storage_paths import resolve_dataset_storage_path

_ROOT_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ROOT_ENV.is_file():
    load_dotenv(_ROOT_ENV)
else:
    load_dotenv()


class Settings(BaseSettings):
    # Keep ingestion resilient in local/dev if env loading fails in a subprocess.
    DATABASE_URL: str = "sqlite:///./statathon.db"
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")


settings = Settings()
engine = create_engine(settings.DATABASE_URL)

upload_dir = os.path.join(os.getcwd(), 'data', 'raw_uploads')
os.makedirs(upload_dir, exist_ok=True)


def _read_excel(source, ext: str) -> pd.DataFrame:
    """`.xlsx` via openpyxl; legacy `.xls` via xlrd (see requirements)."""
    if ext == ".xlsx":
        return pd.read_excel(source, engine="openpyxl")
    if ext == ".xls":
        try:
            return pd.read_excel(source, engine="xlrd")
        except ImportError as e:
            raise ImportError(
                "Reading .xls requires xlrd. Install with: pip install xlrd>=2.0.1"
            ) from e
    raise ValueError(f"Unsupported Excel extension: {ext}")


def _read_csv(source) -> pd.DataFrame:
    """Read CSV as strings to avoid mixed-type DtypeWarning and preserve raw values."""
    return pd.read_csv(source, dtype=str)


def load_file(path: str) -> pd.DataFrame:
    """Load CSV or Excel for `pipelines.orchestrator`."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return _read_csv(path)
    if ext in (".xlsx", ".xls"):
        return _read_excel(path, ext)
    raise ValueError(f"Unsupported file type: {ext}")


def load_dataframe_from_object_bytes(filename: str, body: bytes) -> pd.DataFrame:
    """Parse CSV/XLS/XLSX from in-memory upload (presigned PUT flow)."""
    ext = os.path.splitext(filename)[1].lower()
    bio = io.BytesIO(body)
    if ext == ".csv":
        return _read_csv(bio)
    if ext in (".xlsx", ".xls"):
        return _read_excel(bio, ext)
    raise ValueError(f"Unsupported file type: {ext}")


def dataframe_for_uploaded_dataset(
    dataset_storage_path: str | None,
    dataset_object_key: str | None,
    filename: str,
    object_store: object | None,
) -> pd.DataFrame:
    """
    Load a DataFrame from local disk or object storage.

    Exactly one source must be populated: ``storage_path`` (local ingest) or
    ``object_key`` (presigned PUT to S3/R2/etc.).
    """
    if dataset_object_key and object_store is None:
        raise ValueError("object_key present but ObjectStore unavailable (configure env / boto3)")
    if dataset_object_key:
        raw = object_store.download_object_body(dataset_object_key)
        return load_dataframe_from_object_bytes(filename, raw)
    if dataset_storage_path:
        resolved = resolve_dataset_storage_path(dataset_storage_path)
        if resolved is None:
            raise ValueError("Dataset storage_path is empty")
        return load_file(resolved)
    raise ValueError("Dataset has neither storage_path nor object_key")


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

    df = _read_csv(file_path)
    
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