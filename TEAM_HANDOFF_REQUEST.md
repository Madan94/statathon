# TEAM HANDOFF REQUEST — Extraction + Binder → Trunk Takeover

> **Purpose:** This is the **single document** we need the team to fill in, confirm, and push (as e.g.
> `docs/HANDOFF_EXTRACTION_BINDING.md`) **before they stop active work**. Once this is frozen and pushed,
> we take over Generation / Render / BI / UI on the new deploy trunk and treat everything below as the **gold spec**.
> **Why one doc:** the team is stopping; anything not written here becomes tribal knowledge we can't recover.
> **How to fill:** each item has **What we need**, **Why**, and a **TEAM ANSWER:** line. Short, precise answers win.
> Code pointers we already found are pre-filled so the team only has to **confirm or correct**.

Legend: ☐ = needs team answer · ✅ = we believe this is true, team please confirm · ⚠️ = we suspect a gap/risk.

---

## A. Contract freeze — the S3→S4 handoff (HIGHEST PRIORITY)

Our generation will bind to these. If any field name changes after you stop, our adapter silently mis-maps.

**A1. ✅ Confirm `ExecutionBundle` is THE handoff and is field-frozen.**
- What we need: confirm `binding.executionBundle.v1` is the **stable, official** S4 input, and that we should
  consume it (not the flat stash) as the source of truth.
- Why: we are rewiring generation to consume `ExecutionBundle.plans` instead of re-deriving plans. Found wired at
  `api/report_builder_api/binding_phase_api.py:411` + `GET /{template_id}/{signature}/execution-ready`.
- TEAM ANSWER (yes/no + version + "frozen" or "may still change which fields"): ______

**A2. ☐ Full field spec of `QuestionExecutionPlan`.**
- What we need: the complete, authoritative field list of `QuestionExecutionPlan` (in
  `report_builder/binding/execution_contracts.py`), with types + meaning, especially: how **measures**,
  **dimensions**, **filters** (incl. `filterApplied` semantics), **op/question_type**, **periods/time**, and any
  **normalization/formula** refs are represented.
- Why: this is the exact input to our `QuestionExecutionPlan → AnalyticsPlanRec` adapter (Option C in our plan).
- TEAM ANSWER (paste the field list or point to the definitive lines): ______

**A3. ⚠️ Does `QuestionExecutionPlan` carry presentation/analytic hints, or only execution semantics?**
- What we need: specifically — does a plan say anything about **chart type / preferred visualization / ranking
  direction / top-N**, or is that purely a render/blueprint concern?
- Why: render's `AnalyticsPlanRec` has chart-ish hints; if plans don't carry them, our adapter must fall back to the
  blueprint. We need to know which side owns "how to display."
- TEAM ANSWER: ______

**A4. ☐ `StatisticalContext` spec + how to honor it.**
- What we need: the fields of `StatisticalContext` (weights, CV/MoE, design effect, survey design, rounding rules)
  and your expectation for how downstream (narrator/figures) must **use** them (e.g. always show CV? suppress
  estimates above a CV threshold? rounding conventions?).
- Why: gold MoSPI reports live or die on correct weighting/precision reporting. We want to render this faithfully,
  not reinvent it.
- TEAM ANSWER: ______

**A5. ☐ Readiness semantics: READY / DEGRADED / NOT_READY.**
- What we need: what each status means for generation. Specifically: **must** we refuse to generate on NOT_READY?
  For DEGRADED, what's the expected user-facing behavior (generate with caveats? which caveats)?
- Why: we want generation to honor your readiness gate, not bypass it.
- TEAM ANSWER: ______

**A6. ☐ `lineageIndex` shape + intended use.**
- What we need: structure of `lineageIndex` (question → entities → columns → source) and how you intend the report's
  **provenance drawer** to consume it.
- Why: our render UI has a ProvenanceDrawer; we want it backed by your lineage, not a parallel invention.
- TEAM ANSWER: ______

---

## B. Storage & addressing conventions

**B1. ⚠️ Resolve the two storage layouts under `storage/bindings/`.**
- What we found:
  - Team freeze store (`report_builder/binding/freeze_store.py`): **directory** `storage/bindings/{template_id}__{signature[:16]}/` with `vN.bundle.json`, `vN.binding.json`, `latest.json`.
  - Render generation (`api/report_builder_api/generate_phase_api.py`): **flat files** `storage/bindings/{template_id}__{signature}.{dataset.json|blueprint.json|data.csv|report.output.ast.json|report.html|overrides.json}`.
- What we need: confirm both are intentional and may coexist, OR tell us the one you consider canonical. Also confirm
  whether the flat stash (`dataset.json`/`blueprint.json`/`data.csv`) is **guaranteed** to be written alongside the
  frozen bundle (our E2E depends on both existing).
- Why: we must read the right artifact and not collide namespaces on the trunk.
- TEAM ANSWER: ______

**B2. ☐ The `signature` algorithm.**
- What we need: exactly how `signature` is computed from a dataset (we believe it's a schema/shape hash; `freeze_store`
  truncates to 16 chars). Is it `sha256` over sorted `col:dtype`? Over data? Stable across re-uploads of the same schema?
- Why: generation and any cache/lookup must reproduce the same signature the binder used.
- TEAM ANSWER: ______

**B3. ☐ `template_id` lifecycle.**
- What we need: where `template_id` comes from (extraction output? user upload? DB row id?) and whether it's stable
  across re-extraction of the same source PDF.
- Why: it's half the storage key; we need it to be deterministic for lookups.
- TEAM ANSWER: ______

---

## C. The extraction → binding handoff (your researched gold)

**C1. ☐ How does extraction output reach binding today, and how should it?**
- What we need: the **intended** flow from extraction outputs (`template.ast.json` + `template.blueprint.json`) into
  the binding phase. Is it auto-wired now, or still a manual hand-off? What's the gold design you researched?
- Why: our earlier audit flagged a *manual* handoff as a gap; you said your proposed changes are the main gold. We
  want to build generation to match your intended handoff, and help automate it if that's the goal.
- TEAM ANSWER: ______

**C2. ☐ Authoritative `blueprint.json` shape.**
- What we need: the definitive structure of the blueprint generation reads (topics → questions → entities →
  answerStructure/components), and which fields are **stable** vs **still evolving**.
- Why: render's `narrator`/`filler` and our adapter's blueprint-fallback (A3) read this directly.
- TEAM ANSWER (or point to the schema file + version): ______

**C3. ☐ `DatasetAST` / `ColumnProfile` field stability.**
- What we need: confirm `DatasetAST` (datasetId, sourceFile, rowCount, archetype, columns[], columnGroups[],
  reshape[]) and `ColumnProfile` (name, role, dtype, unit, cardinality, …) field names are frozen.
- Why: generation profiles/typing depend on these exact names.
- TEAM ANSWER: ______

**C4. ☐ `evidence` / `risks` on `EntityBinding` (your Phase 7 additions).**
- What we need: what populates `EntityBinding.evidence` (`[{signal, score, detail}]`) and `risks`
  (`[{code, severity, message}]`), and whether generation/UI should surface them.
- Why: these are new; we don't want to ignore signal you intentionally added, nor misread severity codes.
- TEAM ANSWER (list the `risk.code` values + severities + meanings): ______

---

## D. A frozen golden fixture (so we can verify takeover)

**D1. ☐ One complete, real end-to-end example checked into the repo.**
- What we need (ideally committed under `tests/fixtures/gold_e2e/` or pointed to):
  1. a source PDF (or its extracted `template.ast.json` + `template.blueprint.json`),
  2. the dataset CSV used,
  3. the resulting **frozen `ExecutionBundle`** (`vN.bundle.json`) + the flat stash,
  4. (if you have one) the **expected** generated `report.output.ast.json` you consider correct.
- Why: this is our acceptance test. With it, we can prove the trunk reproduces gold output and catch any regression
  from the merge/adapter. Without it, "gold" is undefined and we're guessing.
- TEAM ANSWER (path(s) or "will add by ____"): ______

**D2. ☐ Which test files are the contract guardians?**
- What we need: the list of tests you consider the **binding/extraction contract tests** (we see
  `tests/test_binding.py`, `tests/test_binding_contracts.py`, `tests/test_template_emit.py`) — confirm these are the
  ones we must keep green and never weaken.
- Why: we'll run these as the tripwire on every team top-up and never edit them to "make things pass."
- TEAM ANSWER: ______

---

## E. Runtime governance (R0–R8) — how BI/generation must call models

**E1. ☐ How should generation/BI invoke LLMs?**
- What we need: the entry point + contract for your `llm_router` (token budget, fallback policy, provider-agnostic
  enrichment — R1/R3/R4/R5). Should all of generation's narration + BI's intent parsing route through it? What env
  flags govern it (`LLM_DISABLED`, model profiles, budgets)?
- Why: to conform to your runtime governance instead of generation/BI calling Gemini directly and blowing budgets.
- TEAM ANSWER (entry function + file + env flags): ______

**E2. ☐ `LLM_DISABLED` end-to-end expectation.**
- What we need: confirm the **intended** behavior when `LLM_DISABLED=1` across extraction/binding (and your view on
  what generation/BI should do): fully deterministic, or specific stages allowed to no-op?
- Why: our verification (G2) runs with `LLM_DISABLED=1`; we need the deterministic contract to be real, and we may
  need to harden generation's scribe/narrator to honor it.
- TEAM ANSWER: ______

---

## F. Ownership, boundaries, and "do not touch"

**F1. ☐ Lane ownership sign-off.**
- What we need: confirm — **we own** `report_builder/generation/**`, `report_builder/generation/render/**`,
  `dashboard/.../report-builder/render/**`, and enhancements to `deep_bi/**` + `agents/**`. **You own**
  `report_builder/` extraction + `report_builder/binding/**`.
- Why: keeps future merges clean and tells us where we may freely change vs. must escalate.
- TEAM ANSWER (agree / adjust): ______

**F2. ☐ "Do not touch" list.**
- What we need: any files/modules we must **not** modify even if tempted (frozen contracts, vault logic, etc.).
- Why: we'd rather build an adapter on our side than break something you consider sacrosanct.
- TEAM ANSWER: ______

**F3. ☐ If we find a genuine bug in your code, what's the protocol?**
- What we need: after you stop, do you want us to (a) patch + document + notify, or (b) only file an issue and wait?
- Why: defines the §C4 "mandatory change" boundary in our plan.
- TEAM ANSWER: ______

---

## G. Loose ends

**G1. ☐ Any in-flight work NOT yet pushed to `report-builder-ui`?**
- Why: we'll base the trunk on the pushed tip; unpushed work would be lost to us. Please push or list it.
- TEAM ANSWER: ______

**G2. ☐ Known limitations / TODOs in extraction + binding we should know.**
- Why: so we don't mistake a known gap for a regression we caused.
- TEAM ANSWER: ______

**G3. ☐ Committed artifacts confirm.**
- What we need: confirm we may untrack `api/statathon.db` (+ gitignore `*.db`) and that `storage/bindings/demo__*`
  may stay as **render fixtures**. Is `.vscode/mcp.json` shared team config (keep) or personal (gitignore)?
- Why: pre-approved by the owner; just confirming nothing breaks your workflow.
- TEAM ANSWER: ______

**G4. ☐ Branch/promotion logistics.**
- What we need: preferred trunk name (we propose `integration/gold-trunk`); who reviews before `main`/`prod`;
  whether you want the trunk to periodically merge your rare future updates or you'll PR into it.
- Why: defines the deploy/maintain process.
- TEAM ANSWER: ______

---

## H. Minimal "we're unblocked" checklist (the must-haves)

If time is short, these five unblock the takeover; the rest can follow:
1. **A1 + A2** — confirm `ExecutionBundle`/`QuestionExecutionPlan` is gold + its field spec.
2. **B1 + B2** — storage layout + signature algorithm.
3. **C1** — the intended extraction→binding handoff.
4. **D1** — one frozen end-to-end golden fixture.
5. **E1** — how to call the LLM router (+ `LLM_DISABLED` contract).

> Everything else hardens correctness and avoids surprises, but with the five above we can stand up the trunk,
> wire the gold adapter, and verify against your golden fixture.
