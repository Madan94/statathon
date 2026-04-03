from core.ingestion import load_file, infer_schema, health_summary
from core.semantic_engine import map_columns_semantic, priority_graph
from core.rule_validator import single_column_rules, normalize_schema
from core.outlier_engine import zscore_outliers, iqr_outliers, risk_bucket
from core.imputation_engine import knn_impute_numeric
from reports.ingestion_reporter import write_ingestion_report
from reports.math_vault import write_math_vault
from reports.narrative_generator import narrative_from_stats
from reports.tamper_proof import write_tamper_proof_pdf
import pandas as pd
import os

def run_pipeline(storage_path: str, report_dir: str, analysis_id: int) -> dict:
    df = load_file(storage_path)
    schema = infer_schema(df)
    health = health_summary(df)
    semantic = map_columns_semantic(list(df.columns))
    priorities = {c: float(i) / max(len(df.columns), 1) for i, c in enumerate(df.columns)}
    graph = priority_graph(list(df.columns), priorities)
    df2 = normalize_schema(df, schema)
    outliers = {}
    for c in df2.columns:
        if schema.get(c) == "numeric":
            outliers[c] = {"zscore": zscore_outliers(df2[c]), "iqr": iqr_outliers(df2[c])}
    df3 = knn_impute_numeric(df2, list(df2.columns))
    stats = {c: float(df3[c].mean()) for c in df3.columns if pd.api.types.is_numeric_dtype(df3[c])}
    os.makedirs(report_dir, exist_ok=True)
    write_ingestion_report(os.path.join(report_dir, f"ingestion_{analysis_id}.json"), health, schema)
    write_math_vault(os.path.join(report_dir, f"vault_{analysis_id}.json"), stats)
    narrative = narrative_from_stats(stats)
    h = write_tamper_proof_pdf(
        os.path.join(report_dir, f"report_{analysis_id}.pdf"),
        f"Analysis {analysis_id}",
        narrative.split("; "),
        {"analysis_id": analysis_id},
    )
    return {"health": health, "semantic": semantic, "graph": graph, "outliers": outliers, "content_hash": h}