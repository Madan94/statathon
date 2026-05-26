import os
os.environ["DATABASE_URL"] = "postgresql://dummy_user:dummy_pass@localhost:5432/dummy_db"
os.environ["AWS_ACCESS_KEY_ID"] = "dummy"
os.environ["AWS_SECRET_ACCESS_KEY"] = "dummy"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["S3_BUCKET"] = "dummy"

import io
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

# =====================================================================
# THE FIX: Inject dummy environment variables BEFORE importing core
# This stops Pydantic Settings() from crashing during the test setup.
# =====================================================================
# Now we can safely import your pipeline!
from core.ingestion import dataframe_for_uploaded_dataset

def test_presigned_url_stream_parsing():
    """
    Verifies that a binary stream mimicking an S3/R2 object body download
    is correctly loaded into an in-memory BytesIO buffer and converted to a DataFrame.
    """
    # 1. Arrange: Define an adversarial mock MoSPI byte stream
    mock_csv_bytes = b"nic_2008,maternal_mort_rt,dist_cd,hh_size,quarter\n0111,12.5,45,4,Q1\n0112,11.2,46,5,Q2"
    
    # Simulate the dataset database tracking object
    mock_dataset = MagicMock()
    mock_dataset.id = "mock_plfs_2026"
    mock_dataset.object_key = "secure/uploads/plfs_data.csv"
    
    # 2. Act: Intercept the real S3 boto3 utility call and swap with our byte stream
    mock_store = MagicMock()
    mock_store.download_object_body.return_value = mock_csv_bytes
    
    # Execute the parsing logic
    df = dataframe_for_uploaded_dataset(
        dataset_storage_path=None,
        dataset_object_key=mock_dataset.object_key,
        filename="plfs_data.csv",
        object_store=mock_store
    )
    
    # 3. Assert: Verify the integrity of the resulting memory container
    assert isinstance(df, pd.DataFrame), "Output must be a native Pandas DataFrame."
    assert not df.empty, "DataFrame should contain parsed records."
    assert list(df.columns) == ["nic_2008", "maternal_mort_rt", "dist_cd", "hh_size", "quarter"], "Column schema layout was corrupted during parsing."
    assert df.shape == (2, 5), "Row/Column layout mismatch."
    assert df["hh_size"].iloc[0] == 4, "Data type coercion failed; numeric string was not cast to integer."

def test_ingestion_empty_stream_handling():
    """
    Ensures that if the stream returns an empty byte buffer, the pipeline
    catches it gracefully.
    """
    mock_empty_bytes = b""
    mock_dataset = MagicMock()
    mock_dataset.object_key = "secure/uploads/empty.csv"
    
    mock_store = MagicMock()
    mock_store.download_object_body.return_value = mock_empty_bytes
    
    with pytest.raises(Exception) as exc_info:
        dataframe_for_uploaded_dataset(
            dataset_storage_path=None,
            dataset_object_key=mock_dataset.object_key,
            filename="empty.csv",
            object_store=mock_store
        )
    assert any(x in str(exc_info.value).lower() for x in ["empty", "no columns to parse"]), f"Unexpected error message: {exc_info.value}"