# Gold Standard — Template & Report Contract

Three cross-referenced files that define the **target shape** of the whole pipeline.
Worked example: a PLFS *Worker Population Ratio* section. All IDs resolve across files
(validated: requiredEntities, biQuery, evidence→analytics, value-free invariant).

| # | File | Role | Values? | Prose? | Produced by |
|---|------|------|---------|--------|-------------|
| ① | [template.ast.json](template.ast.json) | Render **skeleton** — headings, columns, roles, units, formats, palette refs, empty slots wired by `biQuery` | ❌ | ❌ | Extraction |
| ② | [template.blueprint.json](template.blueprint.json) | Analytic **brain** — entities, topics→questions, `analyticsSpec`, answer components, table/figure templates, glossary, palette | ❌ | ❌ | Extraction |
| ③ | [report.output.ast.json](report.output.ast.json) | Filled **instance** — every slot filled + `datasetAST`+`bindingAST`+`analyticsAST`+`evidenceAST` | ✅ | ✅ | Binder (per run) |

## The one rule

> **Values and prose live ONLY in ③.** ① and ② are negatives that print from new data.
> Re-running the binder on a different dataset produces a different ③ from the *same* ①②.

## Traceability chain (every number is auditable)

```
③ content/cell/series.value
      │  provenance.evidenceRef
      ▼
③ evidenceAST   ── analyticsRef ─▶ analyticsAST (plan → execution → rowIds)
      │                                   │ groupBy/measure/filters
      ▼                                   ▼
   columns[] + rowIds[]            datasetAST.columns (role, unit, dtype)
```

## ID conventions

`ent_*` entity · `topic_*` · `q_*` question · `q_*_c#` answer component ·
`p_*` paragraph · `table_*` · `chart_*` · `fig_*` · `tt_*` table-template ·
`ft_*` figure-template · `s_*` style · `plan_*` · `exec_*` · `agg_*` · `rank_*` ·
`m_*` metric · `ev_*` evidence · `ds_*` dataset.
