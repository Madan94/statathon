import numpy as np

from core.json_safe import make_json_safe


def test_make_json_safe_numpy_int64():
    payload = {"row": np.int64(42), "nested": [{"z": np.float64(1.5)}]}
    out = make_json_safe(payload)
    assert out["row"] == 42
    assert isinstance(out["row"], int)
    assert out["nested"][0]["z"] == 1.5


def test_make_json_safe_nan_skewness():
    payload = {"skewness": float("nan"), "entropy": -0.0, "nested": [np.nan]}
    out = make_json_safe(payload)
    assert out["skewness"] is None
    assert out["entropy"] == -0.0
    assert out["nested"][0] is None
