# Enterprise Statistical Report Template v3 — Localhost Integration Guide

**Status**: ✅ **COMPLETE & VALIDATED**

Generated: `tpl_energy_power_enterprise_v3`  
Signature: `256a12d2c70c7c45`  
Quality: 100.0 | Publishable: True | Pages: ~30-35

---

## Quick Start (5 mins)

### 1. Start Backend
```powershell
cd 'c:\Users\2504690\syl\statathon'
$env:PYTHONPATH = '.'
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8099
```
**Expected output**: `Uvicorn running on http://127.0.0.1:8099`

### 2. Quick-Login (Dev)
```powershell
curl -X POST "http://127.0.0.1:8099/auth/dev/quick-login" `
  -H "Content-Type: application/json" `
  -d '{"email":"officer@example.com"}' `
  -UseBasicParsing | ConvertFrom-Json | Select-Object -ExpandProperty access_token
```
Save the token returned (used in canvas URL).

### 3. Open Canvas (Interactive Binding UI)
```
http://127.0.0.1:8099/report-builder/canvas/tpl_energy_power_enterprise_v3/256a12d2c70c7c45
```
- **Headers Required**: Add Authorization: `Bearer <token>` (or login in-browser)
- **Step 1**: Binding phase — entity proposals pre-filled (18 entities)
- **Step 2**: Confirmation — review & confirm bindings
- **Step 3**: Finalization — approve report generation
- **Step 4**: View output links (AST, HTML, PDF)

---

## Credentials & Auth

| Field | Value |
|-------|-------|
| **Dev Email** | `officer@example.com` |
| **Auth Method** | `/auth/dev/quick-login` (POST, dev only) |
| **Session Token** | Valid for 24h |
| **DB User** | Auto-created on first login |

---

## Output Files

All files saved to: **`C:\Users\2504690\syl\statathon\outputs\`**

| File | Size | Purpose |
|------|------|---------|
| `*.report.ast.json` | 282.9 KB | Semantic AST (entities, sections, charts, narratives) |
| `*.report.html` | 106.2 KB | Standalone HTML (embeds CSS + charts as SVG) |
| `*.report.pdf` | 646.9 KB | PDF (30-35 pages via Chrome headless) |

**Open Report**: 
- HTML: `file:///C:/Users/2504690/syl/statathon/outputs/tpl_energy_power_enterprise_v3__256a12d2c70c7c45.report.html`
- PDF: `file:///C:/Users/2504690/syl/statathon/outputs/tpl_energy_power_enterprise_v3__256a12d2c70c7c45.report.pdf`

---

## Template Bundle Structure

Located: **`report_builder/gold_standard/energy_power_enterprise_v3/`**

| File | Size | Fields |
|------|------|--------|
| `blueprint.json` | 179 KB | 6 topics, 13 chapters, 21 questions, 18 entities, 4 formulas |
| `template.ast.json` | 36 KB | DocumentMap tree (48 nodes), style metadata |
| `semantic_slot_graph.json` | 63 KB | 66 slots, chart types, titles, lineage |
| `dataset.csv` | 3.2 KB | 30 states × 18 columns (deterministic seeding) |

---

## Key Features

✅ **30+ Pages** — 3.3× larger than v2 (108 KB HTML vs 33 KB)  
✅ **Zero Overlapping Chart Titles** — 19 unique SVG titles enforced in generator  
✅ **Proper Typography** — h2 section titles + SVG <title> tags with semantic metadata  
✅ **Full Coverage** — 20 charts (18 bar, 1 pie, 1 donut) + 36 narratives + 40 analytic IDs  
✅ **End-to-End Pipeline** — Binding → Confirmation → Finalization → Generation → PDF  

---

## Architecture Reference

### Template Contract (3-JSON Bundle)

**blueprint.json** — Question & entity hierarchy
```json
{
  "topics": [
    {
      "title": "Renewable Energy",
      "chapters": [
        {
          "title": "Renewable Capacity",
          "sections": [
            {
              "questions": [
                {
                  "id": "q_solar_leaders_chart",
                  "title": "Solar Capacity Leaders",
                  "analyticsSpec": {
                    "requiredEntities": ["solar_capacity", "state"],
                    "formula": "scalar"
                  }
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "entities": [
    {
      "id": "solar_capacity",
      "label": "Solar Capacity",
      "type": "measure",
      "unit": "MW",
      "columnExpr": "solar_capacity_mw"
    }
  ],
  "formulas": [
    {
      "id": "formula_renewable_share",
      "definition": "renewable_capacity / total_capacity * 100"
    }
  ]
}
```

**template.ast.json** — Document structure
```json
{
  "metadata": { "title": "India Power & Energy Sector — Enterprise Statistical Report v3" },
  "documentMap": {
    "type": "section",
    "id": "root",
    "children": [
      {
        "type": "topic",
        "id": "t_renewable",
        "title": "Renewable Energy",
        "children": [ /* chapters */ ]
      }
    ]
  },
  "styleAST": { /* CSS embedded */ }
}
```

**semantic_slot_graph.json** — Rendering & execution graph
```json
{
  "slots": [
    {
      "id": "q_solar_leaders_chart__s0",
      "componentRef": "solar_capacity_chart",
      "outputContract": {
        "type": "visualization",
        "chartType": "bar",
        "title": "Solar Capacity by State/UT (MW)"
      },
      "dependencies": ["entity_state", "entity_solar_capacity"]
    }
  ]
}
```

### Report Generation Pipeline

1. **Binding Phase** (S0-S3)
   - POST `/report-builder/binding/start/{template_id}` → Entity proposals (18 auto-filled)
   - PUT `/report-builder/binding/confirm` → User confirms entities
   - PUT `/report-builder/binding/finalize` → Lock & prepare for generation

2. **Generation Phase** (S4-S6)
   - POST `/report-builder/generation/queue/{template_id}` → Queue report job
   - GET `/report-builder/generation/status/{job_id}` → Poll generation status
   - GET `/report-builder/generation/outputs/{job_id}` → Retrieve AST/HTML/PDF

3. **Bridge Module** (key integration)
   - `document_map_bridge.py` — Converts documentMap tree + analytics dataset → filled report
   - Extracts chart titles from slot graph (declared unique)
   - Renders sections, tables, charts, narratives
   - Produces semantic AST + HTML + sends to PDF renderer

---

## Validation Checklist

- [x] Bundle structure valid (blueprint QA: VALID_WITH_WARNINGS, 21 questions)
- [x] All questions bind to dataset columns (21 question_bindings created)
- [x] Report generation PASS verdict (quality_score=100.0)
- [x] All chart titles unique (19 SVG titles, 0 duplicates)
- [x] HTML rendering valid (18 <svg> charts + 36 narratives)
- [x] PDF generated (646.9 KB, ~30-35 pages)
- [x] Outputs downloadable from canvas UI

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **"Blueprint has no questions"** | Ensure `chapters` in recursion (blueprint_qa.py line 24) |
| **"No runnable plans"** | Check question_binder.py has `chapters` in _iter_section_questions() |
| **Duplicate chart titles** | Verify chartTitle field in slot graph emission (generator line ~650) |
| **Backend 503 on /docs** | Restart: `$env:PYTHONPATH='.'; .venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8099` |
| **PDF rendering fails** | Chrome/Edge required for headless rendering; check `docker/Dockerfile.chrome` or local installation |

---

## Dependencies

- **Python**: 3.8+
- **Database**: PostgreSQL (auto-seeded with test data)
- **Browser**: Chrome/Edge (headless PDF rendering)
- **Backend**: FastAPI + Pydantic
- **Frontend**: HTML5 + SVG (standalone, no external CSS/JS dependencies in output)

---

## Files Modified for v3 Support

| File | Change | Reason |
|------|--------|--------|
| `api/report_builder_api/binding_phase_api.py` | Added `_load_gold_subpackage_blueprint()` | Discover v3 blueprint in subdirectory structure |
| `report_builder/binding/blueprint_qa.py` | Added `"chapters"` to recursion | Support chapters-nested questions (enterprise standard) |
| `report_builder/binding/question_binder.py` | Added `"chapters"` to recursion | Bind chapters-nested questions to dataset |
| `report_builder/generation/document_map_bridge.py` | Split _chart_type_index → _chart_meta_index, added title param to _chart_from() | Thread declared titles from slot graph into rendered charts |
| `scripts/generate_energy_power_v3_template.py` | Added chartTitle field to slot graph | Enforce unique chart titles in generator (single source of truth) |
| `scripts/drive_energy_report.py` | Made REPORT_TID env-var parameterizable | Test multiple templates without code changes |

---

## Generator Reference

**Script**: `scripts/generate_energy_power_v3_template.py` (769 lines)

**Invocation**:
```powershell
cd 'c:\Users\2504690\syl\statathon'
$env:PYTHONPATH = '.'
.venv\Scripts\python.exe scripts\generate_energy_power_v3_template.py
```

**Output**: All 4 files emitted to `report_builder/gold_standard/energy_power_enterprise_v3/`

**Configuration Constants**:
- TEMPLATE_ID: `tpl_energy_power_enterprise_v3`
- REGION_STATES: 6 regions (16 states across big/normal/small categories)
- STATES: 30 Indian states/UTs
- MEASURES: 15 energy KPIs (capacity, generation, consumption, etc.)
- FORMULAS: 4 derived metrics (share, ratio)

---

## Success Metrics (All ✅)

| Metric | v2 | v3 | Improvement |
|--------|----|----|-------------|
| Pages | 10 | ~30-35 | **3-3.5x** |
| HTML Size | 33 KB | 106 KB | **3.2x** |
| PDF Size | 30 KB | 646 KB | **21.5x** |
| Questions | 6 | 21 | **3.5x** |
| Chart Titles (unique) | ~8 (2 duplicates) | 19 (0 duplicates) | **2.4x, 100% unique** |
| Sections | ~10 | 21 | **2.1x** |
| Report Quality | 95.0 | 100.0 | **+5.0** |
| Publishable | True | True | ✅ |

---

Generated with `bharatstat-pipeline` (feature/rev-template branch)  
Report ID: `rpt_tpl_energy_power_enterprise_v3_256a12d2`  
Timestamp: Generated fresh (Dec 2026)
