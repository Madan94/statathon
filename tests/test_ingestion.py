import pandas as pd
import tempfile
import os
from core.ingestion import load_file, health_summary

def test_health_summary():
    df = pd.DataFrame({"a": [1, 2, None], "b": ["x", "y", "z"]})
    h = health_summary(df)
    assert h["rows"] == 3
    assert h["missing_per_column"]["a"] == 1