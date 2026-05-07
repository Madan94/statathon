import os
import hashlib
import uuid
import pandas as pd
from sqlalchemy import create_engine
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    model_config = SettingsConfigDict(env_file='.env', extra = 'ignore')

settings = Settings()
engine = create_engine(settings.DATABASE_URL)

upload_dir = os.path.join(os.getcwd(), 'data', 'raw_uploads')
os.makedirs(upload_dir, exist_ok=True)

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