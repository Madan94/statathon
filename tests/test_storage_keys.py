from pathlib import Path
import sys


def _ensure_paths():
    repo = Path(__file__).resolve().parents[1]
    api = repo / "api"
    for p in (str(repo), str(api)):
        if p not in sys.path:
            sys.path.insert(0, p)


def test_generate_object_key_shape():
    _ensure_paths()
    from datasets.storage_keys import generate_object_key

    k = generate_object_key("survey.csv")
    assert k.endswith("survey.csv") or "-" in k
    assert "/" in k
    assert ".csv" in k.lower()
