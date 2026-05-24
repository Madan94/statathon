import pandas as pd

from weights.survey_weights import compute_survey_weight_profile, detect_weight_column


def test_detect_weight_column():
    df = pd.DataFrame({"survey_weight": [1.0, 2.0, 1.0], "income": [10, 20, 30]})
    assert detect_weight_column(df) == "survey_weight"


def test_compute_weighted_means():
    df = pd.DataFrame({"wt": [1.0, 1.0, 2.0], "x": [10.0, 30.0, 20.0]})
    prof = compute_survey_weight_profile(df, {"x": "numeric", "wt": "numeric"})
    assert prof["applied"] is True
    assert "x" in prof["weighted_numeric_means"]
