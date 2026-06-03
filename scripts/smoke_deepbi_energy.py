"""Deep BI smoke test against unified_energy_reserves_dataset.csv."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from deep_bi import ResponseBuilder

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
df = pd.read_csv(os.path.join(repo, "test_data", "unified_energy_reserves_dataset.csv"))
print(f"Dataset: {len(df)} rows, {len(df.columns)} columns")
print(f"Columns: {list(df.columns)}")
print()

# Lightweight schema graph for the dataset (state ↔ resource correlations)
schema_graph = {"edges": [
    {"source": "Total_Reserves", "target": "Proved_Reserves",
     "weight": 0.92, "relationship_type": "CONTAINS"},
    {"source": "Total_Reserves", "target": "Indicated_Reserves",
     "weight": 0.85, "relationship_type": "CONTAINS"},
    {"source": "Total_Reserves", "target": "Inferred_Reserves",
     "weight": 0.78, "relationship_type": "CONTAINS"},
    {"source": "State", "target": "Total_Reserves",
     "weight": 0.80, "relationship_type": "INFLUENCES"},
    {"source": "Resource_Category", "target": "Total_Reserves",
     "weight": 0.86, "relationship_type": "INFLUENCES"},
    {"source": "Resource_Category", "target": "Potential_Capacity_MW",
     "weight": 0.65, "relationship_type": "INFLUENCES"},
]}
column_domains = {
    "Site_ID": "geography", "State": "geography",
    "Resource_Category": "energy", "Unit_of_Measure": "energy",
    "Proved_Reserves": "energy", "Indicated_Reserves": "energy",
    "Inferred_Reserves": "energy", "Total_Reserves": "energy",
    "Potential_Capacity_MW": "energy",
}

builder = ResponseBuilder(schema_graph=schema_graph,
                            column_domains=column_domains)

queries = [
    "Which states have the highest total coal reserves?",
    "Compare proved versus indicated reserves across resource categories",
    "What is the total renewable potential capacity in MW?",
    "Show me outliers in proved reserves",
    "Distribution of total reserves",
    "Which states outperform their expected renewable potential based on population size?",
]

for q in queries:
    print("=" * 78)
    print(f"Q: {q}")
    resp = builder.answer(query=q, df=df, semantic_archetype="energy")
    print(f"   intent.question_type = {resp.intent.question_type}")
    print(f"   intent.concepts       = {resp.intent.concepts}")
    print(f"   intent.confidence     = {resp.intent.confidence:.2f}  (method={resp.intent.method})")
    print(f"   reasoning.concepts    = {resp.reasoning.concepts}")
    print(f"   reasoning.total_w     = {resp.reasoning.total_weight:.2f}")
    print(f"   plan.target_columns   = {resp.plan.target_columns}")
    print(f"   plan.group_columns    = {resp.plan.group_columns}")
    print(f"   plan.steps            =")
    for s in resp.plan.steps:
        print(f"     - {s.op:>10s}  params={s.params}")
    print(f"   execution.results     = {len(resp.execution.results)} ops")
    for r in resp.execution.results[:3]:
        sample = r.value if not isinstance(r.value, list) else r.value[:2]
        print(f"     [{r.op}] {r.explanation}  ->  {sample}")
    print(f"   evidence_count        = {len(resp.evidence)}")
    print(f"   confidence            = {resp.confidence.value:.3f} ({resp.confidence.band})")
    print(f"   narrative             = {resp.narrative[:400]}")
    if resp.final_table:
        print(f"   final_table cols      = {resp.final_table.get('columns')}")
        print(f"   final_table rows      = {len(resp.final_table.get('rows') or [])}")
    if resp.final_chart:
        print(f"   final_chart           = type={resp.final_chart.get('type')} title={resp.final_chart.get('title')}")
