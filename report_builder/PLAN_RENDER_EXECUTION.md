# Report Builder — Render & Customization: DETAILED EXECUTION PLAN

> Companion to `PLAN_RENDER.md` (which holds the locked decisions + architecture).
> This file is the **step-by-step build plan** the agent executes phase by phase.
> Branch: `feature/report-render-customization`. Model: Claude Opus 4.8.
> Cadence: pause + demo + verify after every numbered sub-phase (Rx.y).
> Last updated: 2026-06-09.

---

## 0. Ground truth — the contracts we render (DO NOT DRIFT)

These are the **exact** shapes in `report.output.ast.json` (gold-verified). Every
renderer/component reads these and nothing else. Keep this section authoritative.

```
report.output.ast.json
  metadata { reportId, templateId, generatedAt, locale, period{current,prior,delta},
             status, coverage{questionsTotal,questionsAnswered,bindingsConfirmed} }
  semanticAST.sections[] { sectionId, title, level, order, styleRef, topicRef,
                           children:[<blockId|figureId|tableId>, ...] }     ← DOC OUTLINE
  contentAST.blocks[]   { blockId, kind:"paragraph", styleRef, content:<str>,
                          biQuery, provenance{questionId,componentId,evidenceRef,
                          analyticsRef}, slot{status} }
  tableAST.tables[]     { tableId, templateRef, biQuery, title,
                          columnGroups[]{groupId,label,spanRefs[]},
                          columns[]{columnId,header,role:dimension|measure,entityRef,
                                    group?,unit?,format?,align},
                          rows[]{<columnId>:value, ..., rowIds[]},
                          footnotes[]{noteId,text}, provenance{...}, slot{status} }
  chartAST.charts[]     { chartId, biQuery, chartType, title,
                          xAxis{entityRef,label}, yAxis{entityRef,label,unit},
                          paletteRef, series[]{label, points[]{x,y,color?,rowIds[]}},
                          provenance{...}, slot{status} }
  figureAST.figures[]   { figureId, templateRef, caption, chartRef, styleRef, slot{status} }
  evidenceAST.evidence[]{ evidenceId, questionId, componentId, kind, analyticsRef,
                          columns[], rowIds[], computation, value?, confidence }
  auditAST { binding{...}, warnings[], humanReview{bindingsConfirmedBy,at, edits?[]} }
```

**Rendering invariant:** walk `semanticAST.sections` ordered by `order`; for each
`children` id, dispatch to paragraph (contentAST) / figure (figureAST→chartAST) /
table (tableAST). A value is **traceable** iff it carries `rowIds`/`provenance`.
Numbers are formatted via the column/axis `unit`+`format` (e.g. `percent.1`).

**Format tokens** seen in gold: `format: "percent.1"`, `unit:"percent"`,
`align:"left|right"`, `format:null`. Number system default = **Indian grouping**.

---

## 1. Connective flow (how everything wires, end to end)

```
 BINDING (done)                GENERATION S4–S6 (done)            PRESENTATION (this plan)
 ─────────────                 ────────────────────────           ───────────────────────────
 storage/bindings/             planner→executor→filler→           generation/render/  (R1)
   {tid}__{sig}.dataset.json     narrator→assembler→               theme+numbers+charts+
   .blueprint.json               report.output.ast.json   ──────►  tables+document+blocks
   .data.csv                     (+ report.html minimal)           │
   .review.json                                                    ├─ render_html(report,
                                                                    │     profile, locale) → HTML
   ┌──────────── NEW persisted artifacts (R4/R5) ───────────┐      ├─ render_pdf(...) WeasyPrint (R2)
   │ .profile.json     author defaults (TemplateProfile)    │      └─ render_latex(...) Tectonic (R6)
   │ .overrides.json   per-report (ReportOverrides)         │
   │ .report.v{n}.output.ast.json   versioned edits (R5)    │      generate_phase_api.py  (R2/R4/R5)
   └─────────────────────────────────────────────────────────┘      /render /report.pdf /profile
                                                                     /overrides /edit /versions
                                                                              │
                                                                     dashboard (R3/R4/R5)
                                                                     /report-builder/[tid]/[sig]/preview
                                                                     ReportPreview + ECharts + tables
                                                                     CustomizePanel + EditableField
```

**Effective render input** = `deepMerge(TemplateProfile, ReportOverrides)` applied to
the report AST → `render_html/pdf/latex`. The same merged "effective profile" feeds
the React preview, so web and print never diverge.

---

## 2. Phase map (what each phase delivers + its gate)

| Phase | Deliverable | Gate (must pass) |
|-------|-------------|------------------|
| **R1.1** | `render/` package scaffold; `numbers.py`; `theme.py` | unit tests for Indian/intl/percent + 3 themes; old `render_html` still works via shim; 97 tests green |
| **R1.2** | `svg_charts.py` — 7 chart types + density rules | snapshot SVG per type; >12-cat horizontal fallback; gold chart renders |
| **R1.3** | `tables.py` — column groups, subtotals, show_dash, footnotes, header-repeat | gold WPR-by-state table snapshot; long-table (40 rows) repeats header markup |
| **R1.4** | `document.py` — cover, TOC, running header/footer, page #, fig/table numbering | both archetypes (press-release + chapter) snapshot; numbering correct |
| **R1.5** | `blocks.py` + bilingual `{en,hi}` labels + locale numbers; wire into `render_html` | golden-HTML snapshot for gold report (en + hi); 97 tests green |
| **R2** | WeasyPrint PDF (`render_pdf` rewrite) + `/report.pdf` endpoint + dashboard download | PDF has cover/TOC/headers/page#/repeating headers; structure snapshot; offline |
| **R3** | React preview: `ReportPreview`, `ReportChart`(ECharts), `ReportTable`, `ProvenanceDrawer` | preview structurally matches server HTML for gold; all chart types render |
| **R4** | `TemplateProfile`+`ReportOverrides`+deepMerge; `CustomizePanel`+`SectionReorder`; profile/overrides API | change profile→re-render; persistence round-trips; merge layered |
| **R5** | `EditableField`, override modal, `validate_numbers` gate, versioned instances, `/edit` `/versions` | prose edit rejects bad numbers; override writes audit+flag; versions kept |
| **R6** | `render_latex` (AST→.tex) + Tectonic compile behind `--engine latex` | content parity with WeasyPrint; default path untouched |

---

## 3. PHASE R1 — Render quality (MoSPI-grade, per-question)

### R1.1 — Package scaffold + numbers + theme  ◄ FIRST SLICE
**Goal:** stand up `generation/render/` without breaking anything; foundation utils.

Files (new):
- `report_builder/generation/render/__init__.py`
  - re-exports `render_html`, `render_pdf` (keep public API identical).
- `report_builder/generation/render/numbers.py`
  - `format_value(value, *, unit=None, fmt=None, locale="en-IN", system="indian") -> str`
  - Indian grouping: `12,34,567`; international: `1,234,567`; `percent.N` → `56.3%`;
    `None` → `—` (em dash, configurable per `emptyPolicy`).
  - `parse_format(fmt) -> (kind, decimals)` for tokens like `percent.1`, `number.0`.
  - unit suffix map (percent → `%`, future: `₹`, `MW`, `Mt`).
- `report_builder/generation/render/theme.py`
  - `@dataclass Theme { id, name, palette[], ink, muted, line, accent, fontBody,
      fontHead, pageSize, margins, logoRef }`.
  - `THEMES = {"mospi_navy"(default), "mospi_saffron", "neutral_grey"}`.
  - `get_theme(id|None) -> Theme` (default navy); `theme_css(theme) -> str`.

Refactor:
- `renderer.py`: move `_fmt_value`, `_PALETTE`, `_CSS` usage to call `numbers.py`/
  `theme.py`. Keep `render_html(report, *, title=None)` signature; add optional
  `theme=None, locale="en-IN"` kwargs (defaulted) so nothing else changes yet.

Tests (new) `tests/test_render_numbers_theme.py`:
- Indian vs international grouping; `percent.1`/`percent.0`; negative; None→dash.
- `get_theme` default + 3 presets; `theme_css` contains palette colors.

**Gate R1.1:** new tests pass; `pytest tests/test_generation_s6.py` still green;
full 97-suite green. Commit `feat(render): render/ scaffold + numbers + theme registry`.

---

### R1.2 — SVG chart kit (7 types + density)
**Goal:** replace single bar with a full deterministic SVG kit.

File (new): `report_builder/generation/render/svg_charts.py`
- `render_chart_svg(chart, theme) -> str` dispatching on `chart["chartType"]`:
  - `bar` / `simple_bar`, `grouped_bar`, `stacked_bar`, `stacked_100` (distribution),
    `line` (time-series), `pie`, `donut`.
- Shared layout helper `chart_layout(points|series, *, max_categories=12)`:
  - if categories > 12 → **horizontal** orientation flag; label thinning; legend on.
- Each renderer: axis baseline + gridlines, value labels (auto-hide if thin),
  palette from `theme`/`point.color`/`paletteRef`, `<title>`/`role="img"` a11y.
- Empty series → `empty-slot` placeholder (keep current behavior).

Refactor: `renderer.py._render_figure` calls `render_chart_svg`.

Tests (new) `tests/test_render_charts.py`:
- One snapshot/structural assertion per chart type (rect/line/path/slice counts).
- `grouped_bar` gold (`Rural 56.3`, `Urban 47.1`) → 2 bars, correct colors.
- 15-category bar → horizontal fallback flag in output.
- pie/donut sum-of-angles ≈ 360; stacked_100 each column sums to 100%.

**Gate R1.2:** chart tests pass; gold report still renders (svg present);
97-suite green. Commit `feat(render): SVG chart kit (7 types + density rules)`.

---

### R1.3 — MoSPI tables
**Goal:** long + wide statewise tables with print-correct headers.

File (new): `report_builder/generation/render/tables.py`
- `render_table(table, theme, *, locale, number_system) -> str`:
  - multi-row column-group header (`columnGroups[].spanRefs` → colspan), then column
    header row; measure cells right-aligned, `format_value` applied.
  - **subtotal/total rows bold** when a row has `isTotal`/`col_state in {All-India,…}`
    (configurable matcher) → `<tr class="subtotal">`.
  - `emptyPolicy: show_dash` → blanks become `—`.
  - footnotes `<ul class="footnotes">` with markers (Source/Note).
  - header-repeat: emit `<thead>` as `display:table-header-group` (CSS in theme) so
    WeasyPrint repeats it per page; (web virtualization handled in R3).
- zebra striping + bordered style via theme CSS.

Refactor: `renderer.py._render_table` → delegate to `tables.render_table`.

Tests (new) `tests/test_render_tables.py`:
- gold WPR-by-state: 2-row header (Rural/Urban group + columns), 3 data rows,
  right-aligned `65.1` → `65.1%`, both footnotes present.
- synthetic 40-row table → header markup flagged repeatable; subtotal row bold.
- None cell → `—`.

**Gate R1.3:** table tests pass; gold table snapshot stable; 97-suite green.
Commit `feat(render): MoSPI tables (column groups, subtotals, header-repeat, footnotes)`.

---

### R1.4 — Document chrome
**Goal:** cover, TOC, running header/footer, page numbers, figure/table numbering.

File (new): `report_builder/generation/render/document.py`
- `build_cover(report, theme) -> str` (title, period, reportId, status, logo slot).
- `build_toc(sections) -> str` (CSS `target-counter` based; numbered sections).
- `running_header_footer_css(theme, report) -> str` (`@page` margins boxes: title /
  page N of M / generated date / ministry line).
- `number_figures_tables(report) -> report` pass: assign `Figure {sec}.{seq}` /
  `Table {sec}.{seq}` captions/titles (mirror gold `numbering` templates).
- `build_provenance_appendix(report) -> str` (evidence rowIds table; used by PDF R2).

Refactor: `render_html` composes: `<cover> + <toc> + <sections> (+ appendix opt)`,
with `@page` CSS from `document.py`. Add `render_html(report, *, theme, locale,
include_cover=True, include_toc=True, include_appendix=False)`.

Tests (new) `tests/test_render_document.py`:
- cover contains title+period; TOC lists each section title in order.
- figure/table numbering: `Figure 1.1`, `Table 1.1` assigned.
- press-release archetype (sections w/ prose+figure) and chapter archetype
  (prose+long-table) both produce well-formed HTML (parse check).

**Gate R1.4:** document tests pass; both archetypes render; 97-suite green.
Commit `feat(render): document chrome (cover, TOC, header/footer, numbering)`.

---

### R1.5 — Per-question blocks + bilingual + final wire
**Goal:** one block group per question; `{en,hi}` labels; locale numbers; finalize.

File (new): `report_builder/generation/render/blocks.py`
- `render_question_group(section, report, theme, locale) -> str`:
  heading + prose (contentAST) + figure (figureAST→chartAST) + table (tableAST),
  in `children` order — this is the per-question unit both archetypes use.

Bilingual:
- `numbers.py`/`theme.py`/`tables.py`/`svg_charts.py` accept `locale in {en-IN, hi-IN}`.
- Label resolution helper `loc(label, locale)`: if a label is `{en,hi}` dict → pick;
  else passthrough (back-compat with plain-string gold). Captions/headers/axis
  labels routed through `loc`.
- Devanagari: theme `fontBody/fontHead` includes `Noto Sans Devanagari` fallback.

Wire: `render_html` now fully composed from `document` + `blocks` + `theme` + `numbers`.
`renderer.py` becomes a thin facade re-exporting from `render/` (keep imports stable:
`from report_builder.generation import render_html, render_pdf`).

Tests (new) `tests/test_render_html_golden.py`:
- Golden-HTML snapshot for gold `report.output.ast.json` (en-IN) — structural
  (counts of sections/figures/tables/svg/footnotes), not brittle full-string.
- hi-IN locale: numbers still format; Devanagari font in CSS; labels switch when
  `{en,hi}` provided.
- Back-compat: existing `tests/test_generation_s6.py` assertions still hold.

**Gate R1.5 (R1 EXIT):** all R1 tests pass; `test_generation_s6.py` green; full
97-suite green; manual render of both sample archetypes looks MoSPI-correct.
Commit `feat(render): per-question blocks + bilingual labels; finalize render/ package`.

**R1 done → demo + check-in.**

---

## 4. PHASE R2 — PDF export (WeasyPrint)

- Rewrite `render_pdf(report, *, theme, locale, engine="weasyprint")` to render the
  full R1 HTML (with cover/TOC/appendix on) → WeasyPrint `write_pdf()`.
- `@page` CSS (from `document.py`) drives margins, running header/footer, page #,
  repeating table headers. Provenance appendix on by default for PDF.
- API: add `GET /report-builder/generate-phase/{tid}/{sig}/report.pdf` → streams PDF
  (regenerates from stored report AST + effective profile). Update `generate` to also
  persist nothing new (PDF is on-demand).
- Dashboard: "Download PDF" button on the Step-3 generate panel + (later) preview.
- Tests `tests/test_render_pdf.py` (skip if WeasyPrint missing): PDF magic bytes
  `%PDF`; non-trivial size; structure-level (page count ≥ expected) if parseable.

**Gate R2:** PDF endpoint returns a valid PDF with chrome; offline; 97-suite green.
Commit `feat(render): WeasyPrint PDF export + /report.pdf endpoint`.

---

## 5. PHASE R3 — Enhanced live preview (React)

Files (new) under `dashboard/components/report-builder/render/`:
- `ReportPreview.tsx` — AST → React; walks `semanticAST.sections`; dispatches blocks.
- `ReportChart.tsx` — ECharts wrapper; `chartSpecToOption(chart, theme)` covering the
  7 types + density rules (mirror `svg_charts` logic); lazy-load echarts on route.
- `ReportTable.tsx` — column groups, subtotals, **sticky + repeating header**,
  virtualization for 36+ rows.
- `ProvenanceDrawer.tsx` — click a value → show evidence→analytics→rowIds.
- `dashboard/lib/report/format.ts` — Indian/intl/percent number formatting (parity
  with `numbers.py`).
- Route `dashboard/app/report-builder/[tid]/[sig]/preview/page.tsx` — fetches report
  AST via `generatePhaseApi.getReport`; renders `ReportPreview`; tab to server HTML.

API reuse: existing `GET .../report` (AST) + `GET .../report.html`.

Tests: dashboard type-check + a render smoke (jest/RTL if present) for `ReportChart`
option mapping + `ReportTable` header repeat.

**Gate R3:** preview structurally matches server HTML for gold; all chart types in
ECharts; provenance drawer resolves rowIds. Commit `feat(dashboard): live report preview (ECharts + tables + provenance)`.

---

## 6. PHASE R4 — Customization (author defaults + viewer overrides)

Server:
- `report_builder/generation/profile.py`:
  - `@dataclass TemplateProfile { theme, pageSetup, numberSystem, locale,
      sectionOrder[], includedQuestions[], perQuestion{<qid>:{chartType, tableFormat,
      tone, maxWords}}, frontMatter{cover,foreword,toc}, backMatter{glossary,notes} }`.
  - `@dataclass ReportOverrides` (same shape, sparse).
  - `effective_profile(template_profile, overrides) -> dict` (deep-merge).
  - `apply_profile(report, eff) -> report`: reorder/filter sections, swap chart types,
    apply table formats, set locale/number system, toggle front/back matter.
- Persistence (binding stash): `.profile.json`, `.overrides.json`.
- API: `GET/PUT .../profile`, `PATCH .../overrides`, `POST .../render` (re-render
  HTML/PDF with effective profile).

Dashboard:
- `CustomizePanel.tsx` — theme switcher, page setup, number system, front/back matter,
  per-section show/hide, per-question chart-type + table-format, tone/length.
- `SectionReorder.tsx` — drag-to-reorder + include/exclude toggles (writes overrides).
- Live: panel change → PATCH overrides → re-render preview.

Tests `tests/test_render_profile.py`: deep-merge precedence; `apply_profile` reorders
+ filters + swaps chart type; round-trip persistence.

**Gate R4:** profile change re-renders (web + export); persistence round-trips; both
layers merge correctly; 97-suite green. Commit `feat(render): customization (template profile + report overrides + panel)`.

---

## 7. PHASE R5 — Editing with lock + audit (WYSIWYG phase 2)

Server:
- `report_builder/generation/edit.py`:
  - `apply_edit(report, edit) -> (report, audit_entry)` where
    `edit = {target, field, value, by, reason?}`.
  - prose/label/caption/footnote/header edits: free; prose re-validated by
    `narrator.validate_numbers` against the question's allowed value set.
  - **number edit (override):** requires `reason`; sets `overridden:true` on the
    element; appends to `auditAST.humanReview.edits[] {field, old, new, by, at, reason}`.
  - **versioning:** each save → `report.v{n}.output.ast.json`; bump `metadata.version`;
    keep prior versions; `list_versions(tid, sig)`.
- API: `POST .../edit`, `GET .../versions`, `GET .../report?version=n`.

Dashboard:
- `EditableField.tsx` — inline edit; numbers show lock + provenance; override modal
  (reason required); shows "overridden" badge.
- Version history view (list + restore-as-new).

Tests `tests/test_render_edit.py`: prose edit with hallucinated number → rejected;
valid prose edit → accepted; number override → audit entry + flag + new version;
version list grows; original preserved.

**Gate R5:** edit gate + override audit + versioning all enforced; 97-suite green.
Commit `feat(render): editing with lock + audit + versioned report instances`.

---

## 8. PHASE R6 — Premium LaTeX engine (optional)

- `report_builder/generation/render/latex.py`:
  - `render_latex(report, theme, locale) -> str` (.tex): `\documentclass`, cover,
    `\tableofcontents`, sections; tables via `longtable`+`booktabs` (header repeat
    native); charts via embedded SVG (`\includesvg`) or `pgfplots` from series.
  - `compile_pdf_tectonic(tex) -> bytes` (invoke Tectonic single binary).
- `render_pdf(..., engine="latex")` routes here; default stays `weasyprint`.
- API: `GET .../report.pdf?engine=latex`.
- Tests `tests/test_render_latex.py` (skip if Tectonic missing): .tex contains
  `\begin{longtable}`, `\section`, cover; content parity (sections/tables count).

**Gate R6:** LaTeX path produces a PDF with content parity; default path untouched.
Commit `feat(render): LaTeX/Tectonic premium PDF engine (--engine latex)`.

---

## 9. Cross-cutting rules (keep us on-track)

- **One source of truth:** all formatting/density logic lives once on the server
  (`numbers.py`, `svg_charts.py`, `tables.py`); the React layer mirrors it via small
  `format.ts` + `chartSpecToOption` — never re-derive contracts.
- **Back-compat:** `from report_builder.generation import render_html, render_pdf`
  must keep working at every step; `renderer.py` stays as a facade.
- **No drift from the AST:** renderers read only §0 contracts; if a field is missing,
  degrade gracefully (`empty-slot`, `—`) — never invent values.
- **Provenance preserved:** never drop `rowIds`/`provenance` when transforming for
  display; edits go through `validate_numbers` + audit.
- **Tests are the gate:** every Rx.y ends green (its own tests + the 97-suite) before
  the next starts. Golden snapshots assert structure (counts/markers), not brittle
  full strings.
- **Commits:** one conventional commit per Rx.y; push as we go (branch has upstream).
- **Verify cmd:**
  `$env:PYTHONPATH=(Get-Location).Path+';'+(Join-Path (Get-Location).Path 'api'); $env:LLM_DISABLED='1'; .\.venv\Scripts\python.exe -m pytest tests/test_binding.py tests/test_template_emit.py tests/test_generation_s4.py tests/test_generation_s5a.py tests/test_generation_s5b.py tests/test_generation_s5c.py tests/test_generation_s6.py tests/test_generation_s7_api.py tests/test_render_*.py -q -p no:cacheprovider`

## 10. Tracking ledger (update as we go)

| Sub-phase | Status | Commit | Notes |
|-----------|--------|--------|-------|
| R1.1 numbers+theme | pending | — | first slice |
| R1.2 svg charts | pending | — | |
| R1.3 tables | pending | — | |
| R1.4 document | pending | — | |
| R1.5 blocks+bilingual | pending | — | R1 exit |
| R2 weasyprint pdf | pending | — | |
| R3 react preview | pending | — | |
| R4 customization | pending | — | |
| R5 edit+audit | pending | — | |
| R6 latex | pending | — | optional |
