"""Shared analytics primitives.

These modules are the single source of truth for distributional statistics
and confidence aggregation across:
  * Domain mapping (semantic confidence)
  * Clustering (cluster quality + stability)
  * Anomaly detection (method selection + severity)
  * Imputation (method recommendation + reliability)
  * Validation (violation confidence)

Computing them in one place eliminates the redundant Shapiro / skew / kurtosis
calls scattered across `outliers/`, `imputation/`, and `validation/` today,
and guarantees every subsystem ranks confidence on the same scale.
"""

from .distribution import DistributionProfile, profile_column, profile_dataframe
from .calibration import CalibratedScore, ConfidenceCalibrator, default_calibrator

__all__ = [
    "DistributionProfile",
    "profile_column",
    "profile_dataframe",
    "CalibratedScore",
    "ConfidenceCalibrator",
    "default_calibrator",
]
