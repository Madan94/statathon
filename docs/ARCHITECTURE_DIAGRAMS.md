# BharatStat V2 — Architecture Diagrams (Presentation Pack)

> Two formats per diagram:
> - **Mermaid** — renders directly in VS Code / GitHub / most slide tools.
> - **Eraser.io DSL** — paste into <https://app.eraser.io> → *Diagram as Code* for the premium, icon-rich look.

Color legend: **Inputs** gray · **Phase 1 Extraction** blue · **Phase 2 Binder** amber · **Phase 3 Canvas/Copilot** green · **Agents** teal · **Infrastructure** purple · **Artifacts** rose · **Output** dark.

---

## 1 — Hero: End-to-End System Architecture (Mermaid)

```mermaid
flowchart TB
    PDF["📄 Legacy MoSPI / NSSO PDF"]:::input
    CSV["📊 New Dataset · CSV / DataFrame"]:::input

    subgraph P1["①  PHASE 1 · TEMPLATE EXTRACTION  ·  7-pass, offline-capable"]
        direction LR
        EXT["LayoutLMv3 → Qwen-VL → Document-KG → Two-Loop Questions → Assemble"]:::p1
    end

    A["① template.ast.json<br/>render skeleton · empty slots"]:::artifact
    B["② template.blueprint.json<br/>entities · questions · analyticsSpec"]:::artifact

    subgraph P2["②  PHASE 2 · BINDER  ·  S0 → S6 (human-in-the-loop)"]
        direction LR
        BIND["Profile → Resolve → CONFIRM ★ → Question-bind"]:::p2
    end

    DS["datasetAST"]:::artifact
    BD["bindingAST · human-confirmed<br/>+ coverage report"]:::artifact

    subgraph P3["③  PHASE 3 · CANVAS + COPILOT"]
        direction TB
        AGENT["DeepAgent · multi-agent consensus"]:::agent
        CANVAS["A4 Report Canvas + BI Copilot"]:::p3
        AGENT --> CANVAS
    end

    OUT["③ report.output.ast.json<br/>+ evidenceAST · row-level provenance"]:::artifact
    PDFOUT["📑 Verified PDF · cover · TOC · audit hash"]:::output

    subgraph INF["⚙️ SHARED INFRASTRUCTURE"]
        direction LR
        AK["Arrow Kernel"]:::infra
        RED["Redis STM"]:::infra
        QD["Qdrant LTM"]:::infra
        NEO["Neo4j KG"]:::infra
        RTR["LLM Router<br/>Qwen · Gemini · Groq"]:::infra
    end

    PDF --> P1
    P1 --> A & B
    A & B --> P2
    CSV --> P2
    P2 --> DS & BD
    DS & BD --> P3
    P3 --> OUT --> PDFOUT
    INF -.serves.-> P3

    classDef input fill:#E2E8F0,stroke:#475569,color:#0F172A,stroke-width:2px
    classDef p1 fill:#DBEAFE,stroke:#2563EB,color:#0F172A,stroke-width:2px
    classDef p2 fill:#FEF3C7,stroke:#D97706,color:#0F172A,stroke-width:2px
    classDef p3 fill:#D1FAE5,stroke:#059669,color:#0F172A,stroke-width:2px
    classDef agent fill:#CCFBF1,stroke:#0D9488,color:#0F172A,stroke-width:2px
    classDef infra fill:#EDE9FE,stroke:#7C3AED,color:#0F172A,stroke-width:2px
    classDef artifact fill:#FFE4E6,stroke:#E11D48,color:#0F172A,stroke-width:2px
    classDef output fill:#1E293B,stroke:#0F172A,color:#F8FAFC,stroke-width:2px
```

### Hero — Eraser.io DSL

```eraser
title BharatStat V2 — End-to-End Architecture

Legacy PDF [icon: file-text, color: gray]
New Dataset [icon: database, color: gray]

Phase 1 — Template Extraction [color: blue, icon: scan] {
  Pass 0 Rasterize [icon: image]
  Pass 1 LayoutLMv3 [icon: layout]
  Pass 2 Qwen-VL Entities [icon: eye]
  Pass 2.5 Document KG [icon: git-branch]
  Pass 3 Two-Loop Questions [icon: help-circle]
  Pass 4 Assemble AST [icon: package]
}

Value-Free Template [color: red, icon: file-code] {
  template.ast.json — skeleton [icon: layout-template]
  template.blueprint.json — brain [icon: cpu]
}

Phase 2 — Binder [color: orange, icon: link] {
  S0 Profile [icon: search]
  S1 Resolve cascade [icon: shuffle]
  S2 Confirm — HUMAN [icon: user-check]
  S3 Question-Bind [icon: check-circle]
}

Bound Artifacts [color: red, icon: shield] {
  datasetAST [icon: database]
  bindingAST [icon: git-merge]
}

Phase 3 — Canvas + Copilot [color: green, icon: edit-3] {
  DeepAgent Consensus [icon: cpu]
  A4 Report Canvas [icon: file-text]
  BI Copilot [icon: message-square]
}

Infrastructure [color: purple, icon: server] {
  Arrow Kernel [icon: zap]
  Redis STM [icon: clock]
  Qdrant LTM [icon: book-open]
  Neo4j KG [icon: share-2]
  LLM Router [icon: git-pull-request]
}

Output [color: gray, icon: file-output] {
  report.output.ast.json [icon: file]
  evidenceAST — row-level [icon: list]
  Verified PDF [icon: file-text]
}

Legacy PDF > Phase 1 — Template Extraction
Phase 1 — Template Extraction > Value-Free Template
Value-Free Template > Phase 2 — Binder
New Dataset > Phase 2 — Binder
Phase 2 — Binder > Bound Artifacts
Bound Artifacts > Phase 3 — Canvas + Copilot
Infrastructure > Phase 3 — Canvas + Copilot: serves
Phase 3 — Canvas + Copilot > Output
```

---

## 2 — Phase 1: Template Extraction (7-pass)

```mermaid
flowchart TB
    IN["📄 Legacy PDF"]:::input
    P0["Pass 0 · Rasterize<br/>pdf2image 150dpi + pdfplumber<br/>text · words · tables · headings"]:::p1
    L1["Pass 1 · Layout Detection<br/>LayoutLMv3 · CPU :8001<br/>regions {type, bbox, text}"]:::p1
    P2["Pass 2 · Entity + Structure<br/>Qwen2.5-VL · GPU :8002<br/>50–150 tokens · NO values"]:::p1
    P25["Pass 2.5 · Document KG  ★ PROGRAMMATIC<br/>entity merge · table structure<br/>chapter hierarchy · late-chunking"]:::p1hot
    P26["Pass 2.6 · Entity Classification<br/>dimension · measure · filter · metadata"]:::p1
    P3["Pass 3 · Two-Loop AST · Qwen-VL<br/>L1 questions per section<br/>L2 entity bindings + answerStructure"]:::p1
    P4["Pass 4 · Assemble  ★ PROGRAMMATIC<br/>Enterprise AST (14 subtrees) + blueprint"]:::p1hot
    P5["Pass 5 · Gemini Enrichment<br/>(optional · online · best-effort)"]:::p1opt
    A["① template.ast.json"]:::artifact
    B["② template.blueprint.json"]:::artifact

    IN --> P0 --> L1 --> P2 --> P25 --> P26 --> P3 --> P4 --> P5
    P4 --> A & B
    P5 -.enrich.-> B

    classDef input fill:#E2E8F0,stroke:#475569,color:#0F172A,stroke-width:2px
    classDef p1 fill:#DBEAFE,stroke:#2563EB,color:#0F172A,stroke-width:2px
    classDef p1hot fill:#BFDBFE,stroke:#1D4ED8,color:#0F172A,stroke-width:3px
    classDef p1opt fill:#EFF6FF,stroke:#93C5FD,color:#1E3A8A,stroke-width:1px,stroke-dasharray:5 3
    classDef artifact fill:#FFE4E6,stroke:#E11D48,color:#0F172A,stroke-width:2px
```

### Phase 1 — Eraser.io DSL

```eraser
title Phase 1 — Template Extraction (7-pass)

Legacy PDF [icon: file-text, color: gray]

Pass 0 Rasterize [color: blue, icon: image]
Pass 1 LayoutLMv3 (CPU :8001) [color: blue, icon: layout]
Pass 2 Qwen-VL Entities (GPU :8002) [color: blue, icon: eye]
Pass 2.5 Document KG — PROGRAMMATIC [color: blue, icon: git-branch]
Pass 2.6 Entity Classification [color: blue, icon: tag]
Pass 3 Two-Loop Questions [color: blue, icon: help-circle]
Pass 4 Assemble AST + Blueprint [color: blue, icon: package]
Pass 5 Gemini Enrich (optional) [color: gray, icon: sparkles]

template.ast.json [color: red, icon: layout-template]
template.blueprint.json [color: red, icon: cpu]

Legacy PDF > Pass 0 Rasterize > Pass 1 LayoutLMv3 (CPU :8001) > Pass 2 Qwen-VL Entities (GPU :8002)
Pass 2 Qwen-VL Entities (GPU :8002) > Pass 2.5 Document KG — PROGRAMMATIC > Pass 2.6 Entity Classification
Pass 2.6 Entity Classification > Pass 3 Two-Loop Questions > Pass 4 Assemble AST + Blueprint > Pass 5 Gemini Enrich (optional)
Pass 4 Assemble AST + Blueprint > template.ast.json
Pass 4 Assemble AST + Blueprint > template.blueprint.json
Pass 5 Gemini Enrich (optional) > template.blueprint.json: enrich
```

---

## 3 — Phase 2: Binder (S0 → S6)

```mermaid
flowchart TB
    TPL["② blueprint entities<br/>+ ① skeleton (optional)"]:::artifact
    DF["📊 Dataset · DataFrame"]:::input

    S0["S0 · PROFILE · profiler.py<br/>dtype · role · cardinality · unit<br/>+ wide column-groups → reshape"]:::p2
    S1["S1 · RESOLVE · resolver.py<br/>exact→alias→glossary→synonymKG→embedding<br/>+ ranked alternatives[]"]:::p2
    S2["S2 · CONFIRM  ★ HUMAN · review.py<br/>proposed → confirmed / overridden / rejected<br/>cache by dataset signature"]:::p2hot
    S3["S3 · QUESTION-BIND · question_binder.py<br/>roles→columns · filter values codes⇄labels<br/>periods · status: executable | blocked | degraded"]:::p2

    DS["datasetAST"]:::artifact
    BD["bindingAST + coverage report"]:::artifact

    subgraph DEF["S4 → S6 · downstream contract"]
        direction LR
        S4["S4 · EXECUTE<br/>analyticsAST + evidenceAST"]:::p2dim
        S5["S5 · FILL slots<br/>outputContract"]:::p2dim
        S6["S6 · ASSEMBLE + RENDER → ③"]:::p2dim
        S4 --> S5 --> S6
    end

    DF --> S0
    TPL --> S1
    S0 --> S1 --> S2 --> S3
    S0 --> DS
    S3 --> BD
    BD --> S4

    classDef input fill:#E2E8F0,stroke:#475569,color:#0F172A,stroke-width:2px
    classDef p2 fill:#FEF3C7,stroke:#D97706,color:#0F172A,stroke-width:2px
    classDef p2hot fill:#FDE68A,stroke:#B45309,color:#0F172A,stroke-width:3px
    classDef p2dim fill:#FFFBEB,stroke:#FCD34D,color:#92400E,stroke-width:1px,stroke-dasharray:5 3
    classDef artifact fill:#FFE4E6,stroke:#E11D48,color:#0F172A,stroke-width:2px
```

### Phase 2 — Eraser.io DSL

```eraser
title Phase 2 — Binder (S0 to S6)

blueprint + skeleton [icon: file-code, color: red]
Dataset DataFrame [icon: database, color: gray]

Binder [color: orange, icon: link] {
  S0 Profile [icon: search]
  S1 Resolve cascade [icon: shuffle]
  S2 Confirm — HUMAN [icon: user-check]
  S3 Question-Bind [icon: check-circle]
}

Outputs [color: red, icon: shield] {
  datasetAST [icon: database]
  bindingAST + coverage [icon: git-merge]
}

Downstream Contract [color: gray, icon: clock] {
  S4 Execute — analyticsAST + evidenceAST [icon: cpu]
  S5 Fill slots — outputContract [icon: edit]
  S6 Assemble + Render [icon: package]
}

Dataset DataFrame > S0 Profile
blueprint + skeleton > S1 Resolve cascade
S0 Profile > S1 Resolve cascade > S2 Confirm — HUMAN > S3 Question-Bind
S0 Profile > datasetAST
S3 Question-Bind > bindingAST + coverage
bindingAST + coverage > S4 Execute — analyticsAST + evidenceAST
```

---

## 4 — Phase 3: DeepAgent Consensus + Canvas/Copilot

```mermaid
flowchart LR
    Q["Officer question /<br/>generate request"]:::input

    subgraph AGENTS["DeepAgent · Multi-Agent Consensus Pipeline"]
        direction TB
        PL["PlannerAgent<br/>11 intents · domain hints"]:::agent
        RT["RetrievalAgent<br/>5 sources · parallel"]:::agent
        AN["AnalyticsAgent<br/>agg · corr · trend · forecast · test"]:::agent
        SC["ScribeAgent<br/>grounded · anti-hallucination"]:::agent
        VR["VerifierAgent<br/>recompute every numeric claim"]:::agent
        CE{"ConsensusEngine<br/>verdict = pass?"}:::agenthot
        PL --> RT --> AN --> SC --> VR --> CE
        CE -->|fail · retry ≤ 3| SC
        CE -->|exhausted| DET["Deterministic fallback"]:::agent
    end

    BLK["RenderedBlock<br/>narrative · table · chart · metric<br/>+ verifier badge + provenance"]:::artifact
    CANVAS["A4 Report Canvas<br/>§-numbering · pagination · table-split"]:::p3
    CHAT["BI Copilot<br/>13-tool router → drag-to-insert"]:::p3

    Q --> PL
    CE -->|pass| BLK
    DET --> BLK
    BLK --> CANVAS & CHAT

    classDef input fill:#E2E8F0,stroke:#475569,color:#0F172A,stroke-width:2px
    classDef agent fill:#CCFBF1,stroke:#0D9488,color:#0F172A,stroke-width:2px
    classDef agenthot fill:#99F6E4,stroke:#0F766E,color:#0F172A,stroke-width:3px
    classDef p3 fill:#D1FAE5,stroke:#059669,color:#0F172A,stroke-width:2px
    classDef artifact fill:#FFE4E6,stroke:#E11D48,color:#0F172A,stroke-width:2px
```

### Phase 3 — Eraser.io DSL

```eraser
title Phase 3 — DeepAgent Consensus + Canvas / Copilot

Officer Request [icon: message-circle, color: gray]

DeepAgent Consensus [color: green, icon: cpu] {
  PlannerAgent [icon: git-branch]
  RetrievalAgent [icon: search]
  AnalyticsAgent [icon: bar-chart]
  ScribeAgent [icon: edit-3]
  VerifierAgent [icon: shield]
  ConsensusEngine [icon: refresh-cw]
  Deterministic Fallback [icon: anchor]
}

RenderedBlock [color: red, icon: box]
A4 Report Canvas [color: green, icon: file-text]
BI Copilot [color: green, icon: message-square]

Officer Request > PlannerAgent
PlannerAgent > RetrievalAgent > AnalyticsAgent > ScribeAgent > VerifierAgent > ConsensusEngine
ConsensusEngine > ScribeAgent: fail · retry <= 3
ConsensusEngine > Deterministic Fallback: exhausted
ConsensusEngine > RenderedBlock: pass
Deterministic Fallback > RenderedBlock
RenderedBlock > A4 Report Canvas
RenderedBlock > BI Copilot
```

---

## 5 — Infrastructure & Data Stores

```mermaid
flowchart LR
    subgraph EXEC["⚙️ Execution Layer"]
        AK["Arrow Kernel<br/>PyArrow tables · LRU 8<br/>sidecar :8002"]:::infra
    end
    subgraph MEM["🧠 Memory"]
        STM["STM · Redis · TTL<br/>session state · chat history"]:::infra
        LTM["LTM · Qdrant<br/>MoSPI rulebooks + human corrections"]:::infra
    end
    subgraph GRAPH["🕸️ Knowledge Graph"]
        NEO["Neo4j Community<br/>+ pure-Python payload fallback"]:::infra
    end
    subgraph ROUTER["🔀 LLM Router · env-swappable"]
        QW["Qwen2.5-VL / 3B · local GPU"]:::infra
        GM["Gemini · optional"]:::infraopt
        GR["Groq · optional"]:::infraopt
    end
    AGENT["DeepAgent pipeline"]:::agent
    AK & STM & LTM & NEO & ROUTER --> AGENT

    classDef infra fill:#EDE9FE,stroke:#7C3AED,color:#0F172A,stroke-width:2px
    classDef infraopt fill:#F5F3FF,stroke:#C4B5FD,color:#5B21B6,stroke-width:1px,stroke-dasharray:5 3
    classDef agent fill:#CCFBF1,stroke:#0D9488,color:#0F172A,stroke-width:2px
```

---

## 6 — The 3-File Data Model (intellectual core)

```mermaid
flowchart TB
    subgraph T["VALUE-FREE TEMPLATE · authored once"]
        direction LR
        A["① template.ast.json<br/>layoutAST · geometryAST · styleAST<br/>tableAST (cols, no rows) · chartAST (no series)"]:::artifact
        B["② template.blueprint.json<br/>entities · glossary · palette<br/>topics → questions → analyticsSpec<br/>answerStructure → refs → ①"]:::artifact
    end
    subgraph I["GENERATED INSTANCE · per run"]
        direction TB
        C["③ report.output.ast.json"]:::output
        D["+ datasetAST"]:::artifact
        E["+ bindingAST"]:::artifact
        F["+ evidenceAST · row-level provenance"]:::artifact
        G["analyticsAST · tableAST · chartAST · figureAST<br/>(augmented + refs filled)"]:::artifact
    end
    A -->|cloned + slots filled| C
    B -->|recipe drives fill| C
    C --- D & E & F & G

    classDef artifact fill:#FFE4E6,stroke:#E11D48,color:#0F172A,stroke-width:2px
    classDef output fill:#1E293B,stroke:#0F172A,color:#F8FAFC,stroke-width:2px
```

---

## How to use these in the deck

1. **Slide 4 (overview):** Diagram 1 (Hero). Use the Eraser DSL for the polished, icon-rich render.
2. **Slides 5–7:** Diagram 2 (Phase 1).
3. **Slides 8–9:** Diagram 3 (Phase 2) — emphasise the ★ HUMAN confirm node.
4. **Slides 10–12:** Diagram 4 (agents) + Diagram 5 (infra).
5. **Slide 3 (big idea):** Diagram 6 (3-file model).

**Premium-render tip:** in Eraser.io, after pasting, set *Theme → Clean/Dark*, enable *Rounded* nodes, and export at 2× PNG/SVG for crisp slides.
