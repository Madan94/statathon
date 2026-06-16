"""Dynamic BI query strings from AST template slots + dataset schema (no answer data)."""
from __future__ import annotations

import pandas as pd

from .schema import Figure, MultiAST, Paragraph, Table


def dataset_schema_blurb(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    dtypes = {c: str(df[c].dtype) for c in df.columns[:12]}
    period = ""
    if "year" in df.columns and "month" in df.columns:
        sub = df.copy()
        sub["_y"] = sub["year"].astype(str)
        sub["_m"] = sub["month"].astype(str)
        # Always focus on the LATEST period actually present in the dataset — never
        # a hardcoded date — so the report tracks whatever data was supplied.
        g = sub.groupby(["_y", "_m"]).size().reset_index(name="n")
        g = g.sort_values(["_y", "_m"], ascending=[False, False])
        r = g.iloc[0]
        period = f" Focus on year={r['_y']} month={r['_m']} when filtering."
    return f"Columns: {', '.join(cols)}. Dtypes: {dtypes}.{period}"


def query_for_paragraph(para: Paragraph, df: pd.DataFrame) -> str:
    template = (para.templateQuestion or para.content or "").strip()
    return (
        "Draft one MoSPI official report paragraph. "
        f"{dataset_schema_blurb(df)} "
        f"Template text to replace (same section intent): {template[:600]}. "
        "Run analytics on the dataset; cite only computed values."
    )


def query_for_table(table: Table, df: pd.DataFrame) -> str:
    title = (table.title or table.tableId).strip()
    return (
        "Ranking table for MoSPI report. "
        f"Table title: {title}. {dataset_schema_blurb(df)} "
        "Rank states by index_al or inflation_al as appropriate to the title."
    )


def query_for_figure(fig: Figure, df: pd.DataFrame) -> str:
    cap = (fig.caption or fig.figureId).strip()
    kind = "pie" if any(w in cap.lower() for w in ("share", "distribution", "band")) else "bar"
    return (
        f"Ranking chart ({kind}) for MoSPI report figure. "
        f"Caption: {cap}. {dataset_schema_blurb(df)} "
        f"Group by state; metric from caption intent."
    )


def attach_queries(ast: MultiAST, df: pd.DataFrame) -> None:
    """Set biQuery on every fillable content slot from template + schema."""
    for para in ast.contentAST.paragraphs:
        if para.type == "body":
            if not para.templateQuestion:
                para.templateQuestion = para.content
            para.biQuery = query_for_paragraph(para, df)
    for table in ast.tableAST.tables:
        table.metadata = dict(table.metadata or {})
        table.metadata["biQuery"] = query_for_table(table, df)
    for fig in ast.figureAST.figures:
        fig.description = query_for_figure(fig, df)
