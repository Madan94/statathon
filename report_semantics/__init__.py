"""Report Semantics — Phase 1: Dataset intelligence for report generation.

Modules:
  summarizer          — comprehensive dataset summary object
  metric_detector     — key metric extraction
  chart_selector      — chart type recommendation per column
  narrative_planner   — section plan from dataset profile
"""
from report_semantics.summarizer.dataset_summarizer import compute_dataset_summary
from report_semantics.metric_detector.detector import detect_key_metrics
from report_semantics.chart_selector.selector import select_charts
from report_semantics.narrative_planner.planner import plan_report_sections

__all__ = [
    "compute_dataset_summary",
    "detect_key_metrics",
    "select_charts",
    "plan_report_sections",
]
