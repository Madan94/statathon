# Report Builder — Render & Customization Plan (PLAN_RENDER.md)

> Phase: **③ Generation → Presentation**. Branch: `feature/report-render-customization`
> (forked from `feature/report-generation-phase`, the verified S4–S6 milestone).
> Status: planning locked, implementation pending. Last updated: 2026-06-09.

---

## 0. Where we are

The generation phase (S4–S6) is **done and verified** (97 tests green): a finalized
binding → `report.output.ast.json` (values + prose + full row-level provenance) →
a self-contained offline HTML with inline-SVG charts. The current renderer
(`report_builder/generation/renderer.py`) is intentionally minimal: single bar
chart type, flat tables, one HTML theme, optional WeasyPrint PDF.

This plan covers turning that minimal renderer into a **MoSPI-grade, customizable,
bilingual, print-faithful reporting surface** with a live editable preview.

---

## 1. Target archetypes (from the two sample PDFs in `data/`)

| | `data/test.pdf` — **Press Release** | `data/test2.pdf` — **Statistical Chapter** |
|---|---|---|
| Page | A4 (595×842) | Letter (612×792) |
| Structure | Numbered highlight sections (1, 2, 3…) | Chapters + sections (1.1, 1.3, 1.5…) |
| Per section | Heading + narrative prose + **one chart** | Prose intro + **long wide statewise tables** |
| Chrome | PIB/Ministry masthead, ₹ values, methodology endnote, definitions table | Table numbering ("Table 1.1"), unit captions ("in Million Tonnes", "in MW"), source notes |
| Tables | small (definitions) | dense, bordered, statewise (36+ rows), wide |
| Charts | 12 embedded chart images | few |

**Implication:** the renderer must support BOTH a prose+figure "press-release" flow
and a prose+long-table "statistical-chapter" flow, driven entirely by the
template's `semanticAST` + per-question block groups. Figure/table numbering, unit
captions, source/methodology footnotes, cover, TOC, and running header/footer are
required by both.

---

## 2. Locked decisions

### Rendering
- **Fidelity:** clean modern web preview **and** print-faithful PDF.
- **Per-question layout:** template-driven (`semanticAST`); one block group per
  question = heading + prose + figure + table.
- **Engine direction:** DUAL — server HTML stays canonical (the PDF source) + a
  React preview renderer in the dashboard.
- **Charts:** one `ChartSpec` → two renderers: **SVG** (canonical, server, used in
  HTML + PDF) + **ECharts** (interactive web preview). Types: simple bar, grouped
  bar, stacked bar, 100%-stacked, line/time-series, pie/donut.
  Auto-switch vertical→horizontal bars when categories **> 12**.
- **Tables:** multi-row column-group headers, right-aligned tabular-nums measures,
  `emptyPolicy: show_dash`, markered footnotes (Source/Note), bold subtotal/All-India
  rows when present, **header repeats on page/section overflow** (web + PDF).
- **Numbers:** **Indian grouping (lakh/crore) default**, with a toggle to international.

### PDF
- **Primary engine = WeasyPrint** (HTML/CSS → PDF; reuses our HTML; CSS Paged Media
  gives cover, TOC, running header/footer, page numbers, repeating table headers).
- **Premium engine = LaTeX via Tectonic**, behind `--engine latex`, as a **later
  milestone** (AST → `.tex` with `longtable`+`booktabs` tables, `pgfplots`/embedded
  SVG charts) for publication-grade output. Default path untouched.
- PDF chrome (all): cover page, TOC, running header/footer, page numbers,
  source/footnote citations, provenance appendix.
- Skip Chromium/Playwright (redundant with WeasyPrint).

### Customization
- **Who:** both — author sets template defaults, viewer applies per-report overrides.
- **What:** theme/palette, fonts, logo/branding/cover, section & question order,
  include/exclude questions, chart type per question, table column format
  (units/decimals/grouping/show-hide/sort), narrative tone/length.
- **Persistence:** BOTH — reusable template defaults + per-report-instance overrides.
- **Theme:** named registry; presets **MoSPI Navy (default)**, MoSPI Saffron, Neutral Grey.
- **UI (Phase 1):** settings panel + drag-to-reorder. WYSIWYG inline editing in Phase 2.

### Preview & editing
- **Live React preview** from the report AST; updates as you customize.
- **Editable** prose, labels, captions, headers, footnotes, order, include/exclude,
  chart type, column format — **and numbers are editable too, with audit**.
- Edited prose re-validated by the narrator's `validate_numbers` (cannot introduce a
  number absent from the evidence set without an explicit override).
- **Override of a computed value:** allowed but requires a **reason**, records
  who/when/old→new into `auditAST.humanReview`, and visibly flags "manually overridden".
- **Edit persistence:** a **new versioned report instance** (original preserved).

### Localization
- **Bilingual Hindi + English now.** Structure i18n-ready (string catalogs;
  label fields carry `{ en, hi }`); numbers respect locale grouping.

### Cleanup / merge
- `generation/renderer.py` is **canonical**. Orphans removed
  (`enterprise_renderer.py`, `entity_engine.py`, `_fix_unicode_temp.py`).
- Legacy `exporter.py` (ReportLab, BlockCanvas) to be **retired** once the new
  WeasyPrint path covers its features.

---

## 3. Architecture

### 3.1 One spec, two renderers (charts)
```
chartAST (ChartSpec: type, series[], axes, palette, labels{en,hi}, unit, format)
        │
        ├─► svg_charts.py   → deterministic inline SVG  → HTML + PDF (canonical)
        └─► <ReportChart/>   → ECharts option            → React preview (interactive)
```
Both consume the identical spec, so preview and print never diverge. Density rules
(horizontal fallback >12 categories, label thinning, legend) live in a shared
`chart_layout` helper so SVG and ECharts behave the same.

### 3.2 Renderer evolution (server, Python)
`generation/renderer.py` → split into a small package `generation/render/`:
```
render/
  __init__.py        render_html(report, theme, locale) / render_pdf(...)
  theme.py           ThemeRegistry (navy/saffron/neutral), fonts, palette, page setup
  numbers.py         Indian/international grouping, percent.N, unit suffixes, hi/en
  svg_charts.py      bar / grouped / stacked / 100%-stacked / line / pie / donut
  tables.py          column-group headers, subtotal rows, show_dash, footnotes,
                     header-repeat (CSS `thead{display:table-header-group}` + longtable)
  document.py        cover, TOC (CSS target-counter), running header/footer, page #,
                     figure/table numbering, provenance appendix
  blocks.py          per-question block group (heading+prose+figure+table)
```
WeasyPrint consumes the same HTML+CSS; the `@page`, counters, and
`thead` repetition give all print chrome with no separate layout code.

### 3.3 Customization & theming model
- **TemplateProfile** (author defaults) stored alongside the template:
  `{ theme, pageSetup, numberLocale, sectionOrder[], includedQuestions[],
     perQuestion{chartType, tableFormat, tone, maxWords}, frontMatter, backMatter }`.
- **ReportOverrides** (per instance) — same shape, sparse; merged over the profile
  at render time: `effective = deepMerge(templateProfile, reportOverrides)`.
- Persisted in the binding stash next to the report:
  `storage/bindings/{id}__{sig}.profile.json` / `.overrides.json` / versioned
  `.report.v{n}.output.ast.json`.

### 3.4 Edit / lock / audit
- Each value element keeps `provenance{evidenceRef, analyticsRef, rowIds}`.
- Editing prose → `validate_numbers` gate. Editing a computed number → override
  modal (reason required) → append to `auditAST.humanReview.edits[]`
  `{ field, old, new, by, at, reason }` + set `overridden: true` on the element.
- Each save writes a new `report.v{n}.output.ast.json`; `metadata.version` bumped;
  previous versions retained.

### 3.5 API additions (`generate_phase_api.py` + new endpoints)
```
GET    /report-builder/generate-phase/{tid}/{sig}/profile          read template profile
PUT    /report-builder/generate-phase/{tid}/{sig}/profile          author defaults
PATCH  /report-builder/generate-phase/{tid}/{sig}/overrides        per-report overrides
POST   /report-builder/generate-phase/{tid}/{sig}/render           re-render with effective profile (html/pdf)
POST   /report-builder/generate-phase/{tid}/{sig}/edit             value/prose edit (+audit)
GET    /report-builder/generate-phase/{tid}/{sig}/report.pdf       WeasyPrint PDF
GET    /report-builder/generate-phase/{tid}/{sig}/versions         list report versions
```

### 3.6 Dashboard (Next.js)
```
dashboard/app/report-builder/[tid]/[sig]/preview/page.tsx   live preview + customize panel
dashboard/components/report-builder/render/
  ReportPreview.tsx        AST → React (sections, blocks, figures, tables)
  ReportChart.tsx          ECharts wrapper (ChartSpec → option)
  ReportTable.tsx          long table: sticky + repeating header, subtotals
  CustomizePanel.tsx       theme / page / number / per-section / per-question
  SectionReorder.tsx       drag-to-reorder + include/exclude toggles
  EditableField.tsx        inline edit w/ lock + override-audit (Phase 2)
  ProvenanceDrawer.tsx     value → evidence → analytics → rows
dashboard/lib/i18n/        en.json, hi.json (UI strings)
```

---

## 4. Milestones (priority order)

> Cadence: check in after each milestone with a short demo + verification.

### R1 — Render quality (per-question, MoSPI-grade)  ← start here
- Split `renderer.py` → `render/` package; theme registry (3 presets); Indian numbers.
- Full SVG chart kit (bar/grouped/stacked/100%/line/pie/donut) + density rules.
- MoSPI tables: column groups, subtotals, show_dash, footnotes, header-repeat.
- Cover + TOC + running header/footer + page numbers + figure/table numbering.
- Bilingual label plumbing (`{en,hi}`), locale-aware numbers.
- **Gate:** golden-HTML snapshot tests for both archetypes; visual diff vs sample PDFs;
  existing 97 tests stay green.

### R2 — PDF export (WeasyPrint)
- `render_pdf` via WeasyPrint with CSS Paged Media; provenance appendix.
- `/report.pdf` endpoint; download in dashboard.
- **Gate:** PDF renders cover/TOC/headers/page-#/repeating table headers; byte-stable
  snapshot of structure; offline.

### R3 — Enhanced live preview (React)
- `ReportPreview` + `ReportChart` (ECharts) + `ReportTable`; provenance drawer.
- **Gate:** preview matches server HTML for the gold report; ECharts renders all types.

### R4 — Customization (author defaults + viewer overrides)
- TemplateProfile + ReportOverrides + deep-merge; settings panel + drag-reorder;
  per-question chart-type & table-format; theme switcher.
- **Gate:** changing profile re-renders; persistence round-trips; both layers merge.

### R5 — Editing with lock + audit (Phase 2 WYSIWYG)
- `EditableField`; override modal; `validate_numbers` gate; versioned instances.
- **Gate:** prose edit rejects hallucinated numbers; override writes audit + flag;
  version history preserved.

### R6 — Premium LaTeX engine (optional, `--engine latex`)
- AST → `.tex` (longtable/booktabs + pgfplots/SVG); Tectonic compile.
- **Gate:** parity of content with WeasyPrint output; default path unaffected.

---

## 5. Merge-with-existing notes
- Keep `ast_core/renderer.py` and `report_builder/pipeline.py` (legacy enterprise
  flow) untouched; new work lives under `generation/render/` + dashboard.
- Retire `exporter.py` only after R2 covers cover/TOC/audit for the new AST.
- Reuse `narrator.validate_numbers` for the edit gate (no new validator).
- Reuse the binding stash mechanism for profile/overrides/versions persistence.

## 6. Risks / open items
- WeasyPrint CSS subset vs complex multi-row headers → validate early in R1/R2.
- Bilingual line-height/justification in PDF (Devanagari) → font choice (Noto Sans
  Devanagari) tested in R1.
- ECharts bundle size in the dashboard → lazy-load on the preview route.
- Long-table performance in React (36+ states × 7 cols) → virtualize in R3.
