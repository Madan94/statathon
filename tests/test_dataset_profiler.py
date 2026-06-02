import os
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://dummy_user:dummy_pass@localhost:5432/dummy_db")

_REPO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(_REPO / "api"))
sys.path.insert(1, str(_REPO))

from services.dataset_profiler import profile_dataset, profile_dataset_bytes


SAMPLE_CSV = _REPO / "tests" / "mospi_mock_survey_data.csv"


def test_profile_dataset_local_file():
    profile = profile_dataset(str(SAMPLE_CSV))
    assert profile["row_count"] == profile["rows"]
    assert profile["column_count"] == profile["columns"]
    assert profile["row_count"] > 0
    assert profile["column_count"] > 0
    assert profile["file_size_bytes"] == SAMPLE_CSV.stat().st_size
    assert profile["file_size_mb"] > 0
    assert len(profile["column_list"]) == profile["column_count"]
    assert len(profile["health_summary"]["preview_rows"]) <= 10


def test_profile_dataset_bytes_matches_file():
    body = SAMPLE_CSV.read_bytes()
    from_file = profile_dataset(str(SAMPLE_CSV))
    from_bytes = profile_dataset_bytes(body, SAMPLE_CSV.name)
    assert from_bytes["row_count"] == from_file["row_count"]
    assert from_bytes["column_count"] == from_file["column_count"]
    assert from_bytes["file_size_bytes"] == len(body)


def test_profile_dataset_unsupported_type():
    with pytest.raises(ValueError, match="Unsupported"):
        profile_dataset_bytes(b"not,a,csv", "data.txt")
