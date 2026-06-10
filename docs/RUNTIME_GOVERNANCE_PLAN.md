# Runtime Governance & Model Configuration — Addendum to Extraction Plan v2

> **Purpose:** Stabilize the model/cache/runtime control plane so the extraction compiler (E0-E13) runs on predictable ground.  
> **Scope:** R0-R8 runtime track + .env policy + recommended model profiles + enhanced E-phase integration points  
> **Current runtime score:** 6.5/10  
> **Target:** 9/10

---

## Why Runtime Before Extraction

Even a perfect extraction compiler will fail unpredictably if:
- Qwen hits context overflow silently
- Gemini burns free-tier quota on enrichment calls nobody requested
- Cache serves stale Pass 2 outputs after pipeline code changes
- Key rotation is blind to 429s and daily limits
- Fallbacks happen invisibly (bad entity came from which provider?)
- Upload API doesn't declare fresh/resume mode

**Rule:** Fix the control plane first. Otherwise the team debugs "extraction quality" when the real cause is stale cache, token truncation, or hidden fallback.

---

## What Already Exists (Repo Audit)

| Layer | Status | Location | Gap |
|-------|--------|----------|-----|
| Provider routing | ✅ Good | `llm_router.py` | Older modules bypass it |
| Key pool (KEY_1..KEY_10) | ✅ Exists | `llm_router.py` | Round-robin only, not quota-aware |
| Per-task providers | ✅ Exists | `.env.example` §7 | Missing fallback chains per task |
| Per-task tokens/temp | ✅ Exists | `.env.example` §11 | Not model-aware (Qwen 3B vs Gemini 1M) |
| Vision fallback order | ✅ Exists | `VLM_FALLBACK_ORDER` | Text calls don't cascade |
| Checkpoint store | ✅ Good | `checkpoint_store.py` | Config hash incomplete, mode not API-visible |
| Gemini enrichment | ⚠️ Direct | `gemini_enrichment.py` | Hardwired to Gemini, bypasses router |
| Guided JSON / self-consistency | ✅ Exists | `.env.example` §8b | Good, keep as-is |
| LLM_DISABLED mode | ✅ Exists | `.env.example` §6b | Good, keep as-is |
| Model call observability | ❌ Missing | — | No ledger, no per-run stats |
| Quota-aware rotation | ❌ Missing | — | No RPM/daily tracking per key |
| Runtime config object | ❌ Missing | — | Scattered env reads everywhere |
| Upload runtime declaration | ❌ Missing | — | API doesn't expose mode/profile |

---

## Phase R0: RuntimeConfig Contract

**Location:** `report_builder/model_runtime/__init__.py`, `report_builder/model_runtime/config.py`  
**Effort:** 1 day

### Purpose

Single source of truth for all runtime decisions. Every module reads from this, never from raw `os.getenv()` scattered across files.

### Implementation

```python
# report_builder/model_runtime/config.py

@dataclass
class RuntimeConfig:
    """Resolved runtime configuration. Built once at startup, read everywhere."""
    
    modelProfile: str               # "local_first" | "qwen_gemini" | "cloud_fallback"
    
    # Resolved per-task settings
    taskConfigs: dict[str, TaskConfig]
    
    # Provider health/availability
    providerHealth: dict[str, ProviderHealth]
    
    # Key pool state
    keyPool: KeyPoolState
    
    # Cache policy
    cacheMode: str                  # "fresh" | "resume" | "force" | "debug"
    cacheBackend: str               # "redis" | "file" | "disabled"
    
    # Feature gates
    enrichmentEnabled: bool
    visionFallbackEnabled: bool
    textFallbackEnabled: bool
    guidedJson: bool
    selfConsistency: bool

@dataclass
class TaskConfig:
    """Resolved configuration for one extraction task."""
    task: str
    modality: str                   # "vision" | "text" | "vision_or_text"
    provider: str                   # Resolved provider for this task
    fallbackOrder: list[str]        # Provider cascade
    maxOutputTokens: int
    maxInputChars: int
    temperature: float
    cacheable: bool
    schemaRequired: bool
    
@dataclass
class ProviderHealth:
    provider: str
    healthy: bool
    lastError: str | None
    cooldownUntil: float            # timestamp
    consecutiveFailures: int
```

### Resolution order

```
1. MODEL_PROFILE env → load preset defaults
2. Per-task env overrides (PROVIDER_X, X_MAX_TOKENS, etc.)
3. Key pool availability check
4. Provider health check
→ Final RuntimeConfig
```

### Acceptance criteria

- [ ] No module calls `os.getenv()` for model/provider/token config directly
- [ ] RuntimeConfig built once at pipeline start, passed to all phases
- [ ] Config includes resolved fallback chains per task
- [ ] Config serializable to JSON (included in diagnostics)

---

## Phase R1: Provider-Agnostic Enrichment

**Location:** Refactor `report_builder/gemini_enrichment.py` → `report_builder/semantic_enrichment.py`  
**Effort:** 1 day

### Problem

`gemini_enrichment.py` calls Gemini directly:
```python
_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
```

It activates when `REASONING_PROVIDER=gemini` even if user only wanted Gemini for text fallback, not enrichment.

### Fix

```python
# report_builder/semantic_enrichment.py (renamed/refactored)

def run_enrichment(ast: dict, config: RuntimeConfig) -> dict:
    """Run semantic enrichment if ENRICHMENT_ENABLED=true.
    
    Routes through llm_router, not directly to Gemini.
    Provider determined by: ENRICHMENT_PROVIDER or fallback chain.
    """
    if not config.enrichmentEnabled:
        return ast  # No-op
    
    # All calls go through central router
    result = llm_text_call(
        task="semantic_enrichment",
        prompt=...,
        config=config,
    )
```

### New env vars

```env
# ── Enrichment Control ─────────────────────────────────────────────────────────
# Enrichment is OPTIONAL and OFF by default. It is NOT triggered by provider choice.
ENRICHMENT_ENABLED=false
ENRICHMENT_PROVIDER=gemini
PROVIDER_SEMANTIC_ENRICHMENT=
PROVIDER_ENTITY_ENRICHMENT=
PROVIDER_QUESTION_REPAIR=
```

### Acceptance criteria

- [ ] `gemini_enrichment.py` no longer calls Gemini directly
- [ ] `ENRICHMENT_ENABLED=false` → zero enrichment calls regardless of provider
- [ ] Enrichment works with any provider (Gemini, Groq, OpenAI)
- [ ] No surprise Gemini calls when `REASONING_PROVIDER=gemini`

---

## Phase R2: Quota-Aware Key Manager

**Location:** `report_builder/model_runtime/key_manager.py`  
**Effort:** 2 days

### Current state

Round-robin rotation across KEY_1..KEY_10. No awareness of:
- Requests-per-minute used
- Daily quota remaining
- 429/rate-limit cooldown
- Key exhaustion

### Implementation

```python
@dataclass
class KeyState:
    slotId: int
    provider: str
    label: str
    apiKey: str
    
    # Limits (from env: KEY_N_RPM, KEY_N_DAILY)
    rpmLimit: int               # 0 = unlimited (local)
    dailyLimit: int | None      # None = unlimited
    
    # Live state
    callsThisMinute: int
    callsToday: int
    cooldownUntil: float        # Unix timestamp (0 = available)
    lastErrorCode: str | None
    consecutiveFailures: int
    healthy: bool

def select_key(provider: str, task: str) -> KeyState | None:
    """
    Select best key for this provider+task combination.
    
    Strategy:
    1. Filter keys for this provider
    2. Skip keys in cooldown
    3. Skip keys at RPM limit
    4. Skip keys at daily limit
    5. Among remaining: pick lowest recent usage
    6. If none available: return None (trigger fallback)
    """

def report_key_result(key: KeyState, success: bool, error_code: str | None = None):
    """
    Called after every model call to update key state.
    
    On success: reset consecutiveFailures
    On 429: parse Retry-After header → set cooldown
    On 403/quota: disable key until next day
    On network error: increment failures, short cooldown
    """
```

### New env vars

```env
# ── Key Pool Configuration ─────────────────────────────────────────────────────
# Each key can optionally declare rate limits for quota-aware rotation.
# KEY_N_RPM=0 means unlimited (local models).

KEY_1_PROVIDER=groq
KEY_1_VALUE=gsk_...
KEY_1_NAME=groq_main
KEY_1_RPM=30
KEY_1_DAILY=14400

KEY_2_PROVIDER=groq
KEY_2_VALUE=gsk_...
KEY_2_NAME=groq_alt
KEY_2_RPM=30
KEY_2_DAILY=14400

KEY_3_PROVIDER=gemini
KEY_3_VALUE=AIza...
KEY_3_NAME=gemini_main
KEY_3_RPM=15
KEY_3_DAILY=1500

KEY_4_PROVIDER=openai
KEY_4_VALUE=local
KEY_4_NAME=ollama_local
KEY_4_RPM=0

KEY_5_PROVIDER=openai
KEY_5_VALUE=local
KEY_5_NAME=qwen_local
KEY_5_RPM=0
```

### Acceptance criteria

- [ ] 429 → key enters cooldown (not retried immediately)
- [ ] Daily limit → key disabled until midnight UTC
- [ ] RPM limit → overflow goes to next key or fallback provider
- [ ] All key state visible in diagnostics
- [ ] Local keys (RPM=0) never rate-limited

---

## Phase R3: Token Budget Manager

**Location:** `report_builder/model_runtime/token_budget.py`  
**Effort:** 1 day

### Problem

Current budgets are per-task only (`.env §11`). But Qwen-VL 3B on 2048 context needs MUCH tighter budgets than Gemini on 1M context. Same task, different model → different safe budget.

### Implementation

```python
# Model-aware budget resolution
def resolve_budget(task: str, provider: str, model: str) -> TokenBudget:
    """
    Priority:
    1. Explicit env: ENTITY_EXTRACTION_MAX_TOKENS=256
    2. Model-specific override: QWEN_ENTITY_MAX_OUTPUT=192
    3. Provider default from MODEL_CAPABILITIES
    4. Task default from TASK_PROFILES
    """

MODEL_CAPABILITIES = {
    # These define SAFE limits, not maximums
    "qwen_vl_3b": {"contextWindow": 2048, "safeOutput": 256, "safeInput": 1800},
    "qwen_vl_7b": {"contextWindow": 4096, "safeOutput": 512, "safeInput": 3500},
    "gemma2_9b": {"contextWindow": 8192, "safeOutput": 1200, "safeInput": 6000},
    "gemini_flash": {"contextWindow": 1000000, "safeOutput": 4000, "safeInput": 20000},
    "groq_scout": {"contextWindow": 131072, "safeOutput": 2000, "safeInput": 12000},
    "gpt4o_mini": {"contextWindow": 128000, "safeOutput": 4000, "safeInput": 10000},
}
```

### Prompt truncation per task

```python
PROMPT_STRATEGIES = {
    "entity_extraction": "page_heading + table_headers + entity_candidates (minimal)",
    "question_generation": "topic_title + entities + table_structures (no body)",
    "entity_binding": "question + entity_list + compact_context",
    "gap_fill": "missing_topic + document_map",
    "semantic_enrichment": "full_section_context (only for high-context models)",
}
```

### New env vars

```env
# ── Model-Specific Token Overrides ─────────────────────────────────────────────
# Override per model when global task tokens are too generous for small models.
QWEN_ENTITY_MAX_OUTPUT=192
QWEN_QUESTION_MAX_OUTPUT=384
QWEN_PROMPT_MAX_CHARS=2500
QWEN_IMAGE_MAX_DIM=800
```

### Acceptance criteria

- [ ] Qwen-VL 3B never receives > 2500 char prompts or > 256 output tokens for entity extraction
- [ ] Gemini can use full context when available
- [ ] Prompt truncation is task-aware (different shrinkers per task)
- [ ] Context overflow → shrink + retry (not immediate fallback)

---

## Phase R4: Task-Specific Fallback Policy

**Location:** `report_builder/model_runtime/fallback_policy.py`  
**Effort:** 1 day

### Problem

Current: vision calls cascade through `VLM_FALLBACK_ORDER`. Text calls do NOT cascade — one failure returns None.

### Implementation

```python
def resolve_fallback_chain(task: str, config: RuntimeConfig) -> list[str]:
    """
    Returns ordered list of providers to try for this task.
    
    Source priority:
    1. Explicit env: FALLBACK_ENTITY_EXTRACTION=qwen,gemini,groq
    2. Task profile default
    3. Global VLM_FALLBACK_ORDER (for vision tasks)
    """

FALLBACK_TRIGGERS = {
    "connection_error": True,       # Always fallback
    "rate_limit_429": True,         # Try another key first, then fallback
    "context_overflow": False,      # Shrink prompt first, then retry same
    "json_parse_error": True,       # Retry with repair prompt, then fallback
    "empty_result": True,           # Fallback if task is critical
    "timeout": True,                # Fallback
    "quota_exhausted": True,        # Fallback to different provider
}
```

### New env vars

```env
# ── Per-Task Fallback Chains ───────────────────────────────────────────────────
# Leave blank to use VLM_FALLBACK_ORDER (vision) or REASONING_PROVIDER (text).
FALLBACK_ENTITY_EXTRACTION=qwen,gemini,groq
FALLBACK_QUESTION_GENERATION=qwen,gemini,groq,openai
FALLBACK_ENTITY_BINDING=openai,gemini,groq,qwen
FALLBACK_GAP_FILL=gemini,groq,openai
FALLBACK_SEMANTIC_ENRICHMENT=gemini,openai,groq

# ── Fallback Behavior ─────────────────────────────────────────────────────────
ENABLE_TEXT_FALLBACK=true
ENABLE_VISION_FALLBACK=true
FALLBACK_ON_PARSE_ERROR=true
FALLBACK_ON_RATE_LIMIT=true
FALLBACK_ON_CONTEXT_OVERFLOW=false
FALLBACK_MAX_ATTEMPTS=3
```

### Acceptance criteria

- [ ] Text tasks cascade (not only vision)
- [ ] Rate limit → try another key same provider before fallback provider
- [ ] Context overflow → shrink prompt + retry same model first
- [ ] Fallback chain visible in diagnostics
- [ ] No infinite loops (max attempts enforced)

---

## Phase R5: Cache Policy Cleanup

**Location:** Enhance `report_builder/checkpoint_store.py`  
**Effort:** 1 day

### Problem 1: Incomplete config hash

Current hash includes some vars but misses important cache invalidators.

### Fix: Extend config hash

```python
# Add to checkpoint config hash computation:
HASH_SOURCES = [
    # Models (any change → cache miss)
    "SGLANG_MODEL", "GEMINI_MODEL", "GROQ_MODEL", "OPENAI_MODEL", "OPENAI_BASE_URL",
    
    # Task config (token/temp changes affect output)
    "ENTITY_EXTRACTION_MAX_TOKENS", "QUESTION_GENERATION_MAX_TOKENS",
    "ENTITY_BINDING_MAX_TOKENS", "GAP_FILL_MAX_TOKENS",
    
    # Routing (different provider → different output)
    "VLM_PROVIDER", "REASONING_PROVIDER", "VLM_FALLBACK_ORDER",
    "PROVIDER_ENTITY_EXTRACTION", "PROVIDER_QUESTION_GENERATION",
    
    # Quality params that affect extraction
    "GUIDED_JSON", "SELF_CONSISTENCY", "PDF_DPI", "VLM_MAX_IMAGE_DIM",
    
    # Pipeline version (code changes)
    "EXTRACTION_PIPELINE", "CHECKPOINT_PIPELINE_VERSION",
    
    # Source code hash (already exists)
    "_pipeline_source_hash",
]
```

### Problem 2: Cache mode not visible to API/UI

### Fix: Expose in start response

```python
# In /start response, include:
"runtime": {
    "cacheMode": "fresh",
    "cacheBackend": "redis",
    "redisConnected": True,
    "configHash": "abc123def456",
    "pipelineVersion": "extraction_gold_v2",
}
```

### New env vars

```env
# ── Cache Policy (enhanced) ────────────────────────────────────────────────────
CHECKPOINT_MODE=fresh
CHECKPOINT_PIPELINE_VERSION=extraction_gold_v2
CHECKPOINT_STRICT_VERSION=true
CHECKPOINT_NAMESPACE=dev
```

### Acceptance criteria

- [ ] Model/provider/token changes invalidate cache automatically
- [ ] `CHECKPOINT_MODE=fresh` clears cache for this run
- [ ] Cache hits/misses visible in extraction diagnostics
- [ ] Redis connection status visible in API response
- [ ] No "stale cache causing bad results" debugging sessions

---

## Phase R6: Upload/Start Runtime Declaration

**Location:** Enhance `api/report_builder_api/` start endpoints  
**Effort:** 0.5 days

### Problem

Upload API doesn't expose what runtime decisions were made. Users can't control fresh/resume or provider profile.

### Fix: Accept and return runtime plan

Request:
```json
{
  "file": "energy_stats.pdf",
  "runMode": "fresh",
  "modelProfile": "local_first",
  "cachePolicy": "clear_for_file"
}
```

Response:
```json
{
  "jobId": "job_...",
  "sourceHash": "sha256_...",
  "runtime": {
    "mode": "fresh",
    "modelProfile": "local_first",
    "providers": {
      "entity_extraction": "qwen",
      "question_generation": "qwen",
      "entity_binding": "openai",
      "semantic_enrichment": "disabled"
    },
    "cache": {"backend": "redis", "connected": true, "mode": "fresh"},
    "keyPool": {"groq": 2, "gemini": 1, "openai_local": 1}
  }
}
```

### Acceptance criteria

- [ ] API accepts `runMode` and `modelProfile` parameters
- [ ] Response shows exactly which providers will be used per task
- [ ] User can force fresh extraction (no cache surprises)
- [ ] Runtime plan logged for debugging

---

## Phase R7: Model Call Ledger

**Location:** `report_builder/model_runtime/call_ledger.py`  
**Effort:** 1 day

### Purpose

Every LLM/VLM call recorded. Essential for:
- Debugging bad outputs (which model produced this?)
- Quota tracking (how many Gemini calls this run?)
- Performance tuning (which task is slowest?)
- Cost awareness (how many tokens used?)

### Implementation

```python
@dataclass
class ModelCallRecord:
    runId: str
    timestamp: str
    task: str
    provider: str
    model: str
    keyLabel: str
    
    # Request
    promptChars: int
    maxTokens: int
    hasImage: bool
    schemaMode: bool
    
    # Response
    status: str                 # "success" | "error" | "fallback" | "cache_hit"
    actualTokensApprox: int
    latencyMs: int
    
    # Fallback info
    fallbackUsed: bool
    fallbackFrom: str | None    # Original provider that failed
    fallbackReason: str | None  # "rate_limit" | "timeout" | "parse_error"
    
    # Error info
    errorCode: str | None
    errorMessage: str | None
    
    # Cache
    cacheHit: bool
    cacheKey: str | None
```

### Storage

```
storage/model_calls/{run_id}.jsonl
```

One line per call. Append-only during run. Summary computed at end.

### Run summary (included in diagnostics)

```json
"modelCalls": {
    "total": 42,
    "byProvider": {"qwen": 30, "openai": 8, "gemini": 4},
    "byTask": {"entity_extraction": 20, "question_generation": 12, "entity_binding": 10},
    "fallbacks": 3,
    "errors": 1,
    "cacheHits": 5,
    "totalLatencyMs": 84000,
    "averageLatencyMs": 2000
}
```

### Acceptance criteria

- [ ] Every model call logged (no silent calls)
- [ ] Fallbacks explicitly recorded with reason
- [ ] Per-run summary in extraction diagnostics
- [ ] Cache hits distinguishable from fresh calls
- [ ] Ledger enables "which provider generated entity X?"

---

## Phase R8: Legacy Hardcoded Path Cleanup

**Location:** `report_builder/gemini_enrichment.py`, `report_builder/blueprint.py`  
**Effort:** 1 day

### Modules to refactor

| Module | Issue | Fix |
|--------|-------|-----|
| `gemini_enrichment.py` | Direct Gemini calls | Route through `semantic_enrichment.py` → `llm_router` |
| `blueprint.py` | Direct SGLang/Gemini classification | Route through `llm_router` task calls |
| Any `os.getenv("GEMINI_API_KEY")` outside router | Provider leak | Remove, use RuntimeConfig |
| Hardcoded model defaults in code | Fragile | Move all defaults to `.env.example` only |

### Rule

After R8:
- Only `llm_router.py` and `model_runtime/` know about API keys
- Only `.env.example` declares default model names
- Every other module calls `llm_text_call()` or `llm_vision_call()` with a task name

### Acceptance criteria

- [ ] `grep -r "GEMINI_API_KEY" report_builder/` → only in llm_router/model_runtime
- [ ] `grep -r "gemini-2.5-flash" report_builder/` → only in .env.example / model_profiles
- [ ] All model calls auditable via call ledger
- [ ] No provider-specific code outside router layer

---

## Recommended Model Profiles

### Profile: `local_first` (Development, Free-Tier Safe)

Best for: daily development, no quota burn, GPU workstation.

```env
MODEL_PROFILE=local_first

VLM_PROVIDER=qwen
REASONING_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=gemma2:9b
OPENAI_API_KEY=local

PROVIDER_ENTITY_EXTRACTION=qwen
PROVIDER_QUESTION_GENERATION=qwen
PROVIDER_ENTITY_BINDING=openai
PROVIDER_TOC_EXTRACTION=openai
PROVIDER_GAP_FILL=openai
PROVIDER_FACT_EXTRACTION=openai

ENRICHMENT_ENABLED=false
ENABLE_TEXT_FALLBACK=true
VLM_FALLBACK_ORDER=qwen
FALLBACK_ENTITY_EXTRACTION=qwen
FALLBACK_QUESTION_GENERATION=qwen,openai

# Token budgets (conservative for 3B model)
QWEN_ENTITY_MAX_OUTPUT=192
QWEN_QUESTION_MAX_OUTPUT=384
QWEN_PROMPT_MAX_CHARS=2500
```

**Use case:** Qwen-VL for all vision, Gemma2:9b (via Ollama) for all text reasoning. Zero cloud API calls. No surprise quota.

### Profile: `qwen_groq_hybrid` (Fast, Free Cloud Text)

Best for: when Groq free tier is available, want fast text reasoning.

```env
MODEL_PROFILE=qwen_groq_hybrid

VLM_PROVIDER=qwen
REASONING_PROVIDER=groq

PROVIDER_ENTITY_EXTRACTION=qwen
PROVIDER_QUESTION_GENERATION=qwen
PROVIDER_ENTITY_BINDING=groq
PROVIDER_TOC_EXTRACTION=groq
PROVIDER_GAP_FILL=groq
PROVIDER_FACT_EXTRACTION=groq

ENRICHMENT_ENABLED=false
FALLBACK_ENTITY_BINDING=groq,openai
FALLBACK_GAP_FILL=groq,openai
```

**Use case:** Qwen-VL for vision, Groq (Llama-4-Scout free tier) for all text. Fast, free, good quality text reasoning.

### Profile: `qwen_gemini_enriched` (High Quality, Quota Used)

Best for: high-value production runs where enrichment matters.

```env
MODEL_PROFILE=qwen_gemini_enriched

VLM_PROVIDER=qwen
REASONING_PROVIDER=gemini

PROVIDER_ENTITY_EXTRACTION=qwen
PROVIDER_QUESTION_GENERATION=qwen
PROVIDER_ENTITY_BINDING=gemini
PROVIDER_GAP_FILL=gemini

ENRICHMENT_ENABLED=true
ENRICHMENT_PROVIDER=gemini
PROVIDER_SEMANTIC_ENRICHMENT=gemini
PROVIDER_ENTITY_ENRICHMENT=gemini

FALLBACK_ENTITY_EXTRACTION=qwen,gemini,groq
FALLBACK_QUESTION_GENERATION=qwen,gemini,groq
```

**Use case:** Best quality. Gemini reasoning + enrichment. Uses Gemini quota.

### Profile: `cloud_fallback_full` (Maximum Reliability)

Best for: demo, presentation, must-not-fail scenarios.

```env
MODEL_PROFILE=cloud_fallback_full

VLM_PROVIDER=qwen
REASONING_PROVIDER=groq
VLM_FALLBACK_ORDER=qwen,gemini,groq,openai

FALLBACK_ENTITY_EXTRACTION=qwen,gemini,groq,openai
FALLBACK_QUESTION_GENERATION=qwen,gemini,groq,openai
FALLBACK_ENTITY_BINDING=groq,gemini,openai,qwen
FALLBACK_GAP_FILL=groq,gemini,openai

ENRICHMENT_ENABLED=true
ENRICHMENT_PROVIDER=gemini
ENABLE_TEXT_FALLBACK=true
ENABLE_VISION_FALLBACK=true
```

**Use case:** Every task has full fallback chain. Most expensive but most reliable.

---

## Model Recommendations for MoSPI Extraction

| Task | Recommended Model | Why | Avoid |
|------|-------------------|-----|-------|
| Entity extraction (vision) | Qwen-VL 3B AWQ | Fast, local, good at short structured output with guided_json | Gemini (wastes quota on per-page calls) |
| Question generation (vision) | Qwen-VL 3B AWQ | Already sees page context, guided_json helps structure | Large models (overkill for structured output) |
| Entity binding (text) | Gemma2:9b or Groq Scout | Good text reasoning, doesn't need vision | Qwen-VL (text-only waste of vision model) |
| TOC extraction (text) | Groq Scout or Gemma2:9b | Fast structured text, doesn't need vision | Gemini (too expensive for simple task) |
| Gap fill (text) | Gemini Flash or Groq Scout | Needs strong reasoning for missing content | Qwen 3B (too small context) |
| Semantic enrichment | Gemini Flash | Needs large context, strong reasoning, worth quota | Qwen 3B (too limited) |
| Entity classification | Gemma2:9b or Groq | Simple text classification, fast | Gemini (overkill) |
| Question repair | Groq Scout | Fast text fixing, good at following templates | Qwen-VL (unnecessary vision) |

### Key insight

> **Vision tasks → Qwen-VL locally (free, fast, guided_json)**  
> **Text reasoning → Gemma2:9b locally OR Groq free tier (fast, free)**  
> **High-context reasoning → Gemini Flash (when worth the quota)**  
> **Enrichment → only Gemini, only when explicitly enabled**

---

## Enhanced .env Additions

Add these sections to `.env.example`:

```env
# ══════════════════════════════════════════════════════════════════════════════════
# 20. MODEL RUNTIME GOVERNANCE (new — R0-R8)
# ══════════════════════════════════════════════════════════════════════════════════

# ── Model Profile ─────────────────────────────────────────────────────────────
# Presets: local_first | qwen_groq_hybrid | qwen_gemini_enriched | cloud_fallback_full
# Each preset provides defaults for all settings below. Explicit settings override.
MODEL_PROFILE=local_first

# ── Enrichment Control (R1) ───────────────────────────────────────────────────
# Enrichment is OPTIONAL and OFF by default. NOT triggered by REASONING_PROVIDER.
ENRICHMENT_ENABLED=false
ENRICHMENT_PROVIDER=gemini
PROVIDER_SEMANTIC_ENRICHMENT=
PROVIDER_ENTITY_ENRICHMENT=
PROVIDER_QUESTION_REPAIR=

# ── Key Pool Quota (R2) ───────────────────────────────────────────────────────
# Add RPM and daily limits per key slot for quota-aware rotation.
# KEY_N_RPM=0 means unlimited (local models). Omit for default (30).
# KEY_1_RPM=30
# KEY_1_DAILY=14400
# KEY_2_RPM=15
# KEY_2_DAILY=1500

# ── Model-Specific Token Limits (R3) ──────────────────────────────────────────
# Override global task tokens for models with limited context.
QWEN_ENTITY_MAX_OUTPUT=192
QWEN_QUESTION_MAX_OUTPUT=384
QWEN_PROMPT_MAX_CHARS=2500
QWEN_IMAGE_MAX_DIM=800

# ── Per-Task Fallback Chains (R4) ─────────────────────────────────────────────
# Comma-separated provider list. Tried in order on failure.
FALLBACK_ENTITY_EXTRACTION=qwen,gemini,groq
FALLBACK_QUESTION_GENERATION=qwen,gemini,groq,openai
FALLBACK_ENTITY_BINDING=openai,gemini,groq
FALLBACK_GAP_FILL=gemini,groq,openai
FALLBACK_SEMANTIC_ENRICHMENT=gemini,openai,groq

# ── Fallback Behavior ─────────────────────────────────────────────────────────
ENABLE_TEXT_FALLBACK=true
ENABLE_VISION_FALLBACK=true
FALLBACK_ON_PARSE_ERROR=true
FALLBACK_ON_RATE_LIMIT=true
FALLBACK_ON_CONTEXT_OVERFLOW=false
FALLBACK_MAX_ATTEMPTS=3

# ── Cache Policy (R5) ─────────────────────────────────────────────────────────
# Mode: fresh (clear cache) | resume (use cache) | force (ignore+overwrite) | debug (use+log)
CHECKPOINT_MODE=fresh
CHECKPOINT_PIPELINE_VERSION=extraction_gold_v2
CHECKPOINT_STRICT_VERSION=true

# ── Model Call Ledger (R7) ─────────────────────────────────────────────────────
MODEL_CALL_LEDGER_ENABLED=true
MODEL_CALL_LEDGER_DIR=./storage/model_calls
```

---

## Integration Points with Extraction Plan E0-E13

### E0 (Contract): Add pass-level runtime metadata

```python
@dataclass
class ExtractionPassContract:
    """Each pass declares its runtime dependencies."""
    passName: str
    deterministic: bool             # True = no model calls
    modelTask: str | None           # Which task profile this pass uses
    cacheable: bool
    requiresVision: bool
    fallbackAllowed: bool
    valueLeakageRisk: str           # "none" | "low" | "medium"
```

### TemplateSemanticGraph: Add runtime trace

```python
@dataclass
class RuntimeTrace:
    """Records HOW a graph node was produced (which model, cache hit, fallback?)"""
    task: str
    provider: str
    model: str
    keyLabel: str
    cacheHit: bool
    fallbackUsed: bool
    fallbackFrom: str | None
    latencyMs: int
    promptHash: str
    outputHash: str
```

Graph entities carry `runtimeTraceRef` so debugging can answer: "bad entity came from which VLM call?"

### E1 (Entity Hygiene): Quarantine includes runtime info

```python
@dataclass
class QuarantinedItem:
    text: str
    reason: str
    sourcePage: int
    sourceType: str
    # NEW: which model produced this candidate
    producedBy: RuntimeTrace | None
    recoverable: bool
```

### E7 (Question Compiler): formulaIntent hints for binder

```python
# Add to question analyticsSpec:
"formulaIntent": {
    "type": "GROWTH",           # Helps binder FormulaSpec inference
    "periods": {"current": "2025", "prior": "2024"},
    "requiresDenominator": False
}
```

### E8 (Slot Wiring): Produce crosswalk

```python
# Include in diagnostics or separate file:
"crosswalk": {
    "questionToSlots": {"q_coal_01": ["p_coal_summary", "table_coal_reserves"]},
    "componentToSlot": {"q_coal_01_c1": "p_coal_summary", "q_coal_01_c2": "table_coal_reserves"}
}
```

### E9 (Diagnostics): Include full runtime summary

```json
"runtime": {
    "modelProfile": "local_first",
    "providers": {"entity_extraction": "qwen", "question_generation": "qwen", "entity_binding": "openai"},
    "enrichment": "disabled",
    "cache": {"mode": "fresh", "backend": "redis", "hits": 5, "misses": 37},
    "modelCalls": {"total": 42, "byProvider": {"qwen": 30, "openai": 12}, "fallbacks": 2, "errors": 0},
    "keyPool": {"healthy": 4, "exhausted": 0, "cooldown": 0}
}
```

### E10 (Gold Tests): Include runtime-off tests

```python
class TestOfflineDeterministicExtraction:
    """Gold tests that prove pipeline works without ANY model calls."""
    
    @pytest.fixture(autouse=True)
    def disable_llm(self, monkeypatch):
        monkeypatch.setenv("LLM_DISABLED", "1")
        monkeypatch.setenv("ENRICHMENT_ENABLED", "false")
    
    def test_produces_valid_skeleton(self):
        """Offline extraction still produces valid template.ast.json."""
    
    def test_pdfplumber_entities_survive(self):
        """Table header entities are extracted without VLM."""
    
    def test_value_free_gate_passes(self):
        """Value-free validator passes on offline output."""
```

### E13 (E2E): Prove no surprise cloud calls

```python
def test_local_first_no_gemini_calls(self, monkeypatch):
    """With MODEL_PROFILE=local_first, zero Gemini calls made."""
    monkeypatch.setenv("MODEL_PROFILE", "local_first")
    monkeypatch.setenv("ENRICHMENT_ENABLED", "false")
    
    # Run extraction
    run_extraction(pdf_path)
    
    # Check call ledger
    ledger = load_call_ledger(run_id)
    gemini_calls = [c for c in ledger if c.provider == "gemini"]
    assert len(gemini_calls) == 0, f"Unexpected Gemini calls: {gemini_calls}"
```

---

## Revised Implementation Order (Final)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  WEEK 0: Runtime Governance (run BEFORE extraction work)                         │
│                                                                                 │
│  R0  RuntimeConfig contract (central config object)                             │
│  R1  Provider-agnostic enrichment (stop Gemini bypass)                          │
│  R3  Token budget manager (Qwen safety)                                         │
│  R4  Task-specific fallback policy (text + vision)                              │
│  R5  Cache policy cleanup (stronger hash, visible mode)                         │
│  R8  Legacy hardcoded path cleanup (gemini_enrichment, blueprint.py)            │
│                                                                                 │
│  After Week 0: every model call is centrally governed, visible, and safe        │
├─────────────────────────────────────────────────────────────────────────────────┤
│  WEEK 1: Compiler Foundation                                                     │
│                                                                                 │
│  E0  Extraction contract + pass contracts + runtime metadata                    │
│  E12 Value-free validator (hard gate from day 1)                                │
│  E1  Entity hygiene compiler (with runtime trace + quarantine)                  │
│  E5  Semantic entity ID generator (fingerprint stability)                       │
│                                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│  WEEK 2: Semantic Structure                                                      │
│                                                                                 │
│  E2  Canonical normalization + measure families                                 │
│  E3  Table header semantic compiler (ghost filter + footnotes + hierarchy)      │
│  E4  Statistical context extraction + inheritance + unit confidence             │
│                                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│  WEEK 3: Enrichment + Charts + Questions                                         │
│                                                                                 │
│  E6  Alias & valueDomain enrichment (with scope + negative guard)              │
│  E11 Chart/figure semantic compiler (no values!)                                │
│  E7  Question compiler + deterministic templates + formulaIntent                │
│                                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│  WEEK 4: Validation + Gold Standard                                              │
│                                                                                 │
│  E8  Slot wiring validator + crosswalk                                          │
│  E9  Extraction diagnostics + runtime summary + pass scores                    │
│  E10 Energy gold standard + regression tests + offline tests                   │
│                                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│  WEEK 5: Integration + Observability                                             │
│                                                                                 │
│  R2  Quota-aware key manager (429/daily/RPM tracking)                           │
│  R6  Upload/start runtime declaration (API visibility)                          │
│  R7  Model call ledger (full observability)                                     │
│  E13 Extraction→Binder E2E integration test (with runtime profile assertion)    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Final Score Targets

| Area | Current | After R+E Plan |
|------|---------|----------------|
| Model routing centralization | 6/10 | 9/10 |
| Key/quota management | 4/10 | 8.5/10 |
| Token budget safety | 5/10 | 9/10 |
| Fallback reliability | 5/10 | 9/10 |
| Cache predictability | 6/10 | 9/10 |
| Provider-agnostic enrichment | 3/10 | 9/10 |
| Call observability | 2/10 | 9/10 |
| Upload/runtime visibility | 3/10 | 8.5/10 |
| Entity hygiene | 5.5/10 | 9/10 |
| Table semantics | 5/10 | 9/10 |
| Binder integration | 6/10 | 9/10 |
| **Overall** | **6.2/10** | **9/10** |

---

## The One Rule

> **Build a compiler, not a parser; and run it on a governed model runtime, not scattered free-tier calls.**

```
RuntimeConfig resolves profile
→ CheckpointStore initialized with explicit mode
→ ModelRuntime handles every LLM/VLM call
→ KeyManager rotates quota-aware keys
→ TokenBudgetManager shrinks prompts/outputs
→ FallbackPolicy handles failures
→ CallLedger records everything
→ Extraction compiler produces template.ast + blueprint + diagnostics
→ Binder receives clean, binder-ready contract
→ ExecutionBundle
→ S4-S6
```

Every model call, cache decision, fallback, token budget, and key choice: **visible, env-driven, and task-aware.**
