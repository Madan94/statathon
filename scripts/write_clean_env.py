"""Write a clean ASCII-only .env to the repo root.

This script is the SINGLE source of truth for the .env file.
All model names, API keys, and token budgets are controlled here --
no model names are hardcoded anywhere in the application code.

DESIGN: 4 provider tiers
  1. openrouter  -- paid, OpenAI-compatible API (OPENAI_ prefix)
                    OPENAI_VISION_MODEL + OPENAI_MODEL
  2. groq        -- free tier, OpenAI-compatible (GROQ_ prefix)
                    GROQ_KEYS list rotates round-robin automatically
                    GROQ_MODEL (text) + GROQ_VISION_MODEL (vision fallback)
  3. gemini      -- free tier, native Google API (GEMINI_ prefix)
                    GEMINI_KEYS list rotates round-robin automatically
                    GEMINI_MODEL + GEMINI_VISION_MODEL
  4. local_qwen  -- SGLang/vLLM on localhost, zero cost (SGLANG_ prefix)
                    SGLANG_MODEL handles both text and vision

TASK ROUTING (per task):
  PROVIDER_<TASK>=openai|groq|gemini|qwen
  TASK_<TASK>_MODEL=<model-id>   (blank = use provider global default)

To choose models: run the DEEP_RESEARCH_PROMPT below in your research agent,
then fill in the blank values in the CFG dict.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / ".env"

# =============================================================================
# EDIT BELOW -- the ONLY place model names and keys should appear
# =============================================================================

CFG = {
    # --------------------------------------------------------------------------
    # SECTION 1: Model Profile + Runtime
    # --------------------------------------------------------------------------
    "MODEL_PROFILE": "ec2_hosted_full",
    "SSL_VERIFY": "1",
    "EXTRACTION_COMPILER_V2": "true",
    "EXTRACTION_COMPILER_STRICT": "false",
    "ENRICHMENT_ENABLED": "false",
    "ENRICHMENT_PROVIDER": "groq",
    "PROVIDER_SEMANTIC_ENRICHMENT": "groq",
    "PROVIDER_QUESTION_REPAIR": "groq",

    # --------------------------------------------------------------------------
    # SECTION 2: API Keys
    # --------------------------------------------------------------------------

    # OpenRouter: single paid key
    "OPENROUTER_KEY": "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",

    # Groq: add/remove keys freely -- all rotate round-robin at 30 rpm each
    "GROQ_KEYS": [
        ("arun-official",    "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"),
        ("harish-off",       "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"),
        ("sylesh-personal",  "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"),
        ("sanjay-s",         "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"),
        ("jayasuriya",       "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"),
        ("appa",             "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"),
        ("akash",            "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"),
        ("clg-san",          "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"),
    ],

    # Gemini: add free-tier keys here (GEMINI_KEY_1..N rotation)
    "GEMINI_KEYS": [
        # ("my-gemini-key-1", "AIza..."),  # uncomment and fill
    ],

    "HF_TOKEN": "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",

    # --------------------------------------------------------------------------
    # SECTION 3: Provider routing per task
    # openai=OpenRouter  groq=Groq pool  gemini=Gemini pool  qwen=local
    # --------------------------------------------------------------------------
    "PROVIDER_ENTITY_EXTRACTION":    "openai",
    "PROVIDER_QUESTION_GENERATION":  "openai",
    "PROVIDER_ENTITY_BINDING":       "groq",
    "PROVIDER_ENTITY_CLASSIFICATION":"groq",
    "PROVIDER_TOC_EXTRACTION":       "groq",
    "PROVIDER_GAP_FILL":             "groq",
    "PROVIDER_FACT_EXTRACTION":      "groq",
    "PROVIDER_SEMANTIC_FALLBACK":    "groq",

    # --------------------------------------------------------------------------
    # SECTION 4: Model selection
    # Fill these in after running the DEEP_RESEARCH_PROMPT below.
    # --------------------------------------------------------------------------

    # -- OpenRouter (paid) vision model --
    # Used for: entity_extraction, question_generation (image + text)
    # Research candidates: qwen/qwen3-vl-plus, qwen/qwen2.5-vl-72b-instruct,
    #   google/gemini-flash-1.5-8b, meta-llama/llama-4-scout, mistral/pixtral-12b
    "OPENAI_VISION_MODEL": "qwen/qwen3-vl-plus",

    # -- OpenRouter text model (fallback only -- Groq handles primary text) --
    # Fires when Groq is rate-limited or down
    # Research candidates: qwen/qwen3.5-flash-02-23, deepseek/deepseek-chat-v3-0324,
    #   meta-llama/llama-4-scout, nousresearch/hermes-3-llama-3.1-405b
    "OPENAI_MODEL": "qwen/qwen3.5-flash-02-23",

    "OPENAI_TIMEOUT": "120",
    "OPENAI_RPM": "40",
    "OPENAI_INCLUDE_REASONING": "false",
    "OPENAI_REASONING_EFFORT": "low",

    # -- Groq text model (primary for ALL text tasks) --
    # Research candidates: llama-3.3-70b-versatile, openai/gpt-oss-120b,
    #   deepseek-r1-distill-llama-70b, meta-llama/llama-4-scout-17b-16e-instruct,
    #   qwen-qwq-32b, moonshotai/kimi-k2-instruct, compound-beta-mini
    "GROQ_MODEL": "llama-3.3-70b-versatile",

    # -- Groq vision model (vision fallback chain: OR -> Groq -> local Qwen) --
    # Research candidates: meta-llama/llama-4-scout-17b-16e-instruct,
    #   meta-llama/llama-4-maverick-17b-128e-instruct
    "GROQ_VISION_MODEL": "meta-llama/llama-4-scout-17b-16e-instruct",

    "GROQ_RPM": "30",
    "GROQ_MAX_TOKENS": "8000",
    "GROQ_TIMEOUT": "120",

    # -- Gemini (free tier, used rarely as fallback) --
    # Research candidates: gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-flash-8b
    "GEMINI_MODEL": "gemini-2.5-flash",
    "GEMINI_VISION_MODEL": "gemini-2.5-flash",
    "GEMINI_ENRICHMENT": "false",
    "GEMINI_RPM": "60",

    # -- Local Qwen SGLang (zero cost, last-resort fallback) --
    "SGLANG_ENDPOINT": "http://localhost:8002",
    "SGLANG_MODEL": "Qwen/Qwen2.5-VL-3B-Instruct-AWQ",
    "SGLANG_TIMEOUT": "300",
    "SGLANG_TEMPERATURE": "0.1",
    "SGLANG_MAX_TOKENS": "2048",
    "SGLANG_DECOMPOSED": "true",
    "SGLANG_BACKEND": "sglang",
    "SGLANG_MEM_FRACTION": "0.42",

    # --------------------------------------------------------------------------
    # SECTION 5: Per-task model overrides
    # "" = use provider global default (OPENAI_VISION_MODEL / GROQ_MODEL / etc.)
    # Set a specific model-id here to override for just that task.
    # --------------------------------------------------------------------------
    "TASK_ENTITY_EXTRACTION_MODEL":    "",
    "TASK_QUESTION_GENERATION_MODEL":  "",
    "TASK_ENTITY_BINDING_MODEL":       "",
    "TASK_ENTITY_CLASSIFICATION_MODEL":"",
    "TASK_TOC_EXTRACTION_MODEL":       "",
    "TASK_GAP_FILL_MODEL":             "",
    "TASK_FACT_EXTRACTION_MODEL":      "",
    "TASK_SEMANTIC_FALLBACK_MODEL":    "",
    "TASK_SEMANTIC_ENRICHMENT_MODEL":  "",
    "TASK_QUESTION_REPAIR_MODEL":      "",

    # --------------------------------------------------------------------------
    # SECTION 6: Token budgets
    # --------------------------------------------------------------------------
    "ENTITY_EXTRACTION_MAX_TOKENS":     "320",
    "ENTITY_EXTRACTION_TEMPERATURE":    "0.0",
    "QUESTION_GENERATION_MAX_TOKENS":   "512",
    "QUESTION_GENERATION_TEMPERATURE":  "0.15",
    "ENTITY_BINDING_MAX_TOKENS":        "1024",
    "ENTITY_BINDING_TEMPERATURE":       "0.0",
    "ENTITY_CLASSIFICATION_MAX_TOKENS": "512",
    "ENTITY_CLASSIFICATION_TEMPERATURE":"0.0",
    "TOC_EXTRACTION_MAX_TOKENS":        "4096",
    "TOC_EXTRACTION_TEMPERATURE":       "0.1",
    "GAP_FILL_MAX_TOKENS":              "8192",
    "GAP_FILL_TEMPERATURE":             "0.2",
    "GAP_FILL_INCLUDE_REASONING":       "true",
    "FACT_EXTRACTION_MAX_TOKENS":       "4096",
    "FACT_EXTRACTION_TEMPERATURE":      "0.1",
    "SEMANTIC_FALLBACK_MAX_TOKENS":     "8192",
    "SEMANTIC_FALLBACK_TEMPERATURE":    "0.2",
    "SEMANTIC_FALLBACK_INCLUDE_REASONING": "true",
    "QUESTION_REPAIR_MAX_TOKENS":       "2048",
    "QUESTION_REPAIR_TEMPERATURE":      "0.1",

    # --------------------------------------------------------------------------
    # SECTION 7: Image + prompt size (cost levers for OpenRouter vision)
    # --------------------------------------------------------------------------
    "VLM_MAX_IMAGE_DIM":     "640",
    "QWEN_IMAGE_MAX_DIM":    "640",
    "QWEN_PROMPT_MAX_CHARS": "1600",
    "QWEN_ENTITY_MAX_OUTPUT":"192",
    "QWEN_QUESTION_MAX_OUTPUT":"320",

    # --------------------------------------------------------------------------
    # SECTION 8: Fallback chains
    # --------------------------------------------------------------------------
    "FALLBACK_ENTITY_EXTRACTION":   "openai,groq,qwen",
    "FALLBACK_QUESTION_GENERATION": "openai,groq,qwen",
    "FALLBACK_ENTITY_BINDING":      "groq,openai,gemini",
    "FALLBACK_GAP_FILL":            "groq,openai,gemini",
    "FALLBACK_FACT_EXTRACTION":     "groq,openai,gemini",
    "FALLBACK_SEMANTIC_FALLBACK":   "groq,openai,gemini",
    "FALLBACK_SEMANTIC_ENRICHMENT": "groq,gemini,openai",
    "VLM_FALLBACK_ORDER":           "openai,groq,qwen",
    "ENABLE_TEXT_FALLBACK":         "true",
    "ENABLE_VISION_FALLBACK":       "true",
    "FALLBACK_ON_PARSE_ERROR":      "true",
    "FALLBACK_ON_RATE_LIMIT":       "true",
    "FALLBACK_ON_CONTEXT_OVERFLOW": "false",
    "FALLBACK_MAX_ATTEMPTS":        "2",

    # --------------------------------------------------------------------------
    # SECTION 9: Infrastructure (rarely changed)
    # --------------------------------------------------------------------------
    "LAYOUTLM_ENDPOINT": "http://13.201.122.188:8001",
    "LAYOUTLM_TIMEOUT": "300",
    "LAYOUTLM_PORT": "8001",
    "LAYOUTLM_MODEL_ID": "Kwan0/layoutlmv3-base-finetune-DocLayNet-100k",
    "EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
    "NEO4J_ENABLED": "true",
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "mospi_secure_password",
    "NEO4J_DATABASE": "neo4j",
    "CHECKPOINT_ENABLED": "true",
    "CHECKPOINT_MODE": "fresh",
    "CHECKPOINT_PIPELINE_VERSION": "extraction_gold_v3_ec2_hosted",
    "CHECKPOINT_STRICT_VERSION": "true",
    "CHECKPOINT_NAMESPACE": "dev",
    "CHECKPOINT_DIR": "./checkpoints",
    "REDIS_URL": "redis://localhost:6379/0",
    "REDIS_CHECKPOINT_PREFIX": "ckpt",
    "REDIS_CHECKPOINT_TTL_HOURS": "168",
    "REDIS_CHECKPOINT_TTL_LLM_HOURS": "24",
    "DATABASE_URL": "postgresql://postgres.sheygkgekdafgesmzbnf:dDLNQHH1YCXxhDNT@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres",
    "DB_NULL_POOL": "true",
    "DB_POOL_SIZE": "2",
    "DB_POOL_MAX_OVERFLOW": "3",
    "DB_POOL_TIMEOUT": "30",
    "DB_POOL_RECYCLE": "20",
    "DB_CONNECT_TIMEOUT": "10",
    "DB_ECHO_POOL": "false",
    "STORAGE_PROVIDER": "s3",
    "S3_BUCKET": "statathon-templates-bucket",
    "AWS_ACCESS_KEY_ID": "AKIAXUNHCP65YGPNC6EH",
    "AWS_SECRET_ACCESS_KEY": "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",
    "AWS_REGION": "eu-north-1",
    "IMMUTABLE_VAULT_REQUIRED": "true",
    "REPORT_STORAGE_PATH": "./storage/reports",
    "UPLOAD_STORAGE_PATH": "./storage/uploads",
    "REPORT_TEMPLATE_DIR": "./storage/templates",
    "HUGGINGFACE_HUB_CACHE": "./model/cache",
    "OUTPUT_DIR": "./outputs",
    "SECRET_KEY": "hKb2woDzSKJeG7IbGeI4mdh+8n6vOcJxUQNdHFmWx4VvuuNmpHu3XvXTw5ESxFA0",
    "APP_ENV": "development",
    "AUTH_REQUIRED": "true",
    "DEV_AUTH_ENABLED": "true",
    "DEV_TEST_EMAIL": "officer@example.com",
    "DEV_TEST_PASSWORD": "TestOfficer123!",
    "DEV_TEST_OTP": "123456",
    "DEV_TEST_FULL_NAME": "Test Officer",
    "DEV_TEST_OFFICER_ROLE": "analyst",
    "CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
    "JWT_ACCESS_MINUTES": "30",
    "JWT_REFRESH_DAYS": "14",
    "OTP_LENGTH": "6",
    "OTP_TTL_MINUTES": "10",
    "OTP_MAX_ATTEMPTS": "5",
    "NEXT_PUBLIC_API_URL": "http://localhost:8000",
    "MAIL_INTERNAL_SECRET": "madhanstathon",
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "lifeofpi234@gmail.com",
    "SMTP_PASS": "iakpsdnqdrxpnlvj",
    "SMTP_FROM": "BharatStat <lifeofpi234@gmail.com>",
    "EXTRACTION_PIPELINE": "v2",
    "PDF_DPI": "150",
    "POPPLER_PATH": r'"C:\\Users\\SANJAY S\\Downloads\\Release-26.02.0-0\\poppler-26.02.0\\Library\\bin"',
    "TESSERACT_CMD": r'"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"',
    "ENTITY_MIN_LENGTH": "4",
    "ENTITY_MAX_LENGTH": "80",
    "ENTITY_FUZZY_MATCH_THRESHOLD": "0.70",
    "ENTITY_SIMILARITY_THRESHOLD": "0.85",
    "INFERENCE_CONFIDENCE_THRESHOLD": "0.30",
    "REVIEW_MIN_TOPICS": "2",
    "REVIEW_MIN_QUESTIONS": "3",
    "REVIEW_MIN_ENTITIES": "5",
    "REVIEW_MIN_CONFIDENCE": "0.4",
    "PIB_ENTITY_CAP": "25",
    "PIB_TABLE_CAP": "0",
    "PIB_Q_PER_CHAPTER": "2",
    "STAT_ENTITY_CAP": "80",
    "STAT_TABLE_CAP": "30",
    "STAT_Q_PER_CHAPTER": "3",
    "MAX_CHAPTERS_LOOP1": "20",
    "GUIDED_JSON": "1",
    "GUIDED_JSON_BACKEND": "outlines",
    "SELF_CONSISTENCY": "1",
    "SELF_CONSISTENCY_THRESHOLD": "0.6",
    "LLM_DISABLED": "",
    "EXTRACTION_EMIT_LEGACY": "",
    "LOG_LEVEL": "INFO",
}

# =============================================================================
# DEEP RESEARCH PROMPT
# Paste into your research agent to get evidence-based model recommendations.
# =============================================================================

DEEP_RESEARCH_PROMPT = """
# BharatStat AI Pipeline -- Model Selection Research Brief

## 1. System Overview

BharatStat is a statistical report extraction and generation pipeline for Indian
government documents (PLFS annual reports, energy statistics, PIB press releases).
It has two workloads: VISION (extract from PDF page images) and TEXT (structured JSON
from text prompts). We need the best cost-effective model for each of 4 providers.

## 2. Workload Specifications

### VISION tasks (OpenRouter -- paid per token)
Tasks: entity_extraction, question_generation
Input per call: 1 image at 640x640 px (~546 image tokens) + text prompt (~400 tokens)
  = ~946 input tokens per call
Output per call: entity JSON ~320 tokens + question JSON ~512 tokens = ~832 output tokens
Frequency: 10-30 calls per document (documents are 11-30 pages)
Quality: must accurately OCR statistical tables, % values, year labels from dense images
Format: structured JSON output required (no free-form text)
Language: English + Hindi mixed text in some documents
Key figures: LFPR 57.3%, UR 3.2%, WPR 54.2%, state names, sector labels

### TEXT tasks (Groq -- free tier primary)
Tasks: entity_binding, entity_classification, toc_extraction, gap_fill,
       fact_extraction, semantic_fallback, question_repair
Input: text prompts, 1K-8K tokens
Output: structured JSON, 512-8192 tokens depending on task
Frequency: 10-40 calls per document
Quality: must produce valid JSON reliably; handles statistical domain vocabulary
Language: English only
Context window needed: >=32K tokens

## 3. Provider Constraints

### OpenRouter (paid, 1 key, ~40 rpm)
- Vision model: MUST support image input (multimodal required)
- Text model: fallback only (fires when Groq is down/rate-limited)
- Cost target: <$0.001 per page for vision (entity + question calls combined)
  - At 640px: input ~946 tok + output ~832 tok per page
  - Max affordable: $0.50 per 1M input, $2.00 per 1M output (rough ceiling)
- Must be available via openrouter.ai API
- PRIORITY: find models with current DISCOUNT pricing (>30% off list)
  Check: https://openrouter.ai/models (filter by multimodal + discount)
- Must support response_format / JSON mode

### Groq (free tier, 8 keys rotating, effective 240 rpm)
- TEXT ONLY tasks (no vision required)
- Must support structured output / JSON mode reliably
- Must handle 4096-8192 output tokens without truncation
- Context window >= 32K input tokens required
- Latency goal: <1s TTFT for 1K-input prompts
- Free tier limits per key: 30 rpm, 6000 TPM (tokens per minute) -- KEY CONSTRAINT
  With 8 keys: 240 rpm effective, 48000 TPM effective
- PRIORITY: most capable model that fits within free tier limits
- Evaluate all currently available models: llama-3.3-70b-versatile,
  openai/gpt-oss-120b, deepseek-r1-distill-llama-70b,
  meta-llama/llama-4-scout-17b-16e-instruct, llama-4-maverick,
  qwen-qwq-32b, moonshotai/kimi-k2-instruct, compound-beta,
  mistral-saba-24b, playai-tts, etc.
- Also evaluate: which Groq model is best for VISION fallback (multimodal)

### Gemini (free tier, N keys, used rarely)
- Both vision and text (rare fallback when OR + Groq both fail)
- Free tier: 15 rpm per key, 1M tokens/day per key
- Must support image input for vision fallback
- Evaluate: gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-flash-8b,
  gemini-1.5-flash, any other free-tier options

### Local Qwen SGLang (already configured -- no research needed)
- Qwen/Qwen2.5-VL-3B-Instruct-AWQ, zero cost, last resort

## 4. Quality Requirements
- Entity extraction F1 > 0.80 on statistical domain (tables, %, years, state names)
- JSON schema compliance > 95% (structured output mode required)
- Must not hallucinate entity IDs or invent values not in the source
- Temperature 0.0 for JSON extraction, 0.1-0.2 for generative tasks

## 5. Current defaults (to beat or confirm)
- OPENAI_VISION_MODEL: qwen/qwen3-vl-plus
- OPENAI_MODEL (fallback text): qwen/qwen3.5-flash-02-23
- GROQ_MODEL: llama-3.3-70b-versatile
- GROQ_VISION_MODEL: meta-llama/llama-4-scout-17b-16e-instruct
- GEMINI_MODEL: gemini-2.5-flash
- GEMINI_VISION_MODEL: gemini-2.5-flash

## 6. Required Output Format

For each recommendation, provide:
```
OPENAI_VISION_MODEL=<exact-model-id>
  Reason: <why best for dense statistical table OCR>
  Cost/1000 pages: $<X.XX> (input=<N>tok + output=<N>tok per page)
  Discount: <% off if any>
  JSON reliability: <high/medium/low>

OPENAI_MODEL=<exact-model-id>
  Reason: <why best text fallback>
  Cost/1M tokens: $<in>/$<out>

GROQ_MODEL=<exact-model-id>
  Reason: <why best for structured JSON text tasks>
  Free tier fit: <RPM used / TPM used per key>
  Max output tokens: <N>
  JSON reliability: <high/medium/low>

GROQ_VISION_MODEL=<exact-model-id>
  Reason: <why best vision fallback on Groq>

GEMINI_MODEL=<exact-model-id>
  Reason: <why>
  Free tier: <rpm/day limits>

GEMINI_VISION_MODEL=<exact-model-id>
  Reason: <why>
```

Also list any models currently on >30% discount on OpenRouter that would be
suitable for either vision or text tasks, with their current discounted prices.
"""


# =============================================================================
# GENERATOR -- do not edit below this line
# =============================================================================

def _build_lines() -> list[str]:
    c = CFG
    groq_keys = c["GROQ_KEYS"]      # list of (name, key) tuples
    gemini_keys = c["GEMINI_KEYS"]  # list of (name, key) tuples

    lines = [
        "# ==============================================================================",
        "# BharatStat V3 -- Environment Configuration",
        "# ==============================================================================",
        "# Generated by scripts/write_clean_env.py  --  edit ONLY that file.",
        "#",
        "# Provider tiers:",
        "#   openai  = OpenRouter (paid)      OPENAI_VISION_MODEL / OPENAI_MODEL",
        "#   groq    = Groq (free, N-key RR)  GROQ_MODEL / GROQ_VISION_MODEL",
        "#   gemini  = Gemini (free, N-key RR) GEMINI_MODEL / GEMINI_VISION_MODEL",
        "#   qwen    = Local SGLang (free)     SGLANG_MODEL",
        "# ==============================================================================",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 1. MODEL PROFILE + RUNTIME GOVERNANCE",
        "# ------------------------------------------------------------------------------",
        "",
        f"MODEL_PROFILE={c['MODEL_PROFILE']}",
        f"SSL_VERIFY={c['SSL_VERIFY']}",
        f"EXTRACTION_COMPILER_V2={c['EXTRACTION_COMPILER_V2']}",
        f"EXTRACTION_COMPILER_STRICT={c['EXTRACTION_COMPILER_STRICT']}",
        "",
        f"ENRICHMENT_ENABLED={c['ENRICHMENT_ENABLED']}",
        f"ENRICHMENT_PROVIDER={c['ENRICHMENT_PROVIDER']}",
        f"PROVIDER_SEMANTIC_ENRICHMENT={c['PROVIDER_SEMANTIC_ENRICHMENT']}",
        "PROVIDER_ENTITY_ENRICHMENT=groq",
        f"PROVIDER_QUESTION_REPAIR={c['PROVIDER_QUESTION_REPAIR']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 2. API KEY POOL",
        "# ------------------------------------------------------------------------------",
        "",
        "# Slot 1: OpenRouter (vision + text fallback -- paid)",
        "KEY_1_PROVIDER=openai",
        f"KEY_1_VALUE={c['OPENROUTER_KEY']}",
        "KEY_1_NAME=openrouter-main",
        f"KEY_1_RPM={c['OPENAI_RPM']}",
        "KEY_1_DAILY=",
        "",
    ]

    # Groq keys: slots 2..N
    slot = 2
    for name, key in groq_keys:
        lines += [
            f"KEY_{slot}_PROVIDER=groq",
            f"KEY_{slot}_VALUE={key}",
            f"KEY_{slot}_NAME={name}",
            "",
        ]
        slot += 1

    # Local Qwen: last slot
    lines += [
        f"KEY_{slot}_PROVIDER=qwen",
        f"KEY_{slot}_VALUE=local",
        f"KEY_{slot}_NAME=local-docker-qwen",
        f"KEY_{slot}_RPM=0",
        f"KEY_{slot}_DAILY=",
        "",
        "# Legacy single-key fallbacks (used if no KEY slot found for provider)",
        "GEMINI_API_KEY=",
        "GOOGLE_API_KEY=",
        f"GROQ_API_KEY={groq_keys[0][1] if groq_keys else ''}",
        f"HF_TOKEN={c['HF_TOKEN']}",
        "",
        "# Gemini multi-key pool: GEMINI_KEY_1..N (round-robin -- add free-tier keys below)",
    ]
    for i, (name, key) in enumerate(gemini_keys, 1):
        lines.append(f"GEMINI_KEY_{i}={key}  # {name}")
    if not gemini_keys:
        lines.append("# GEMINI_KEY_1=AIza...  # paste your free-tier Gemini API key")
    lines.append("")
    lines.append("")

    lines += [
        "# ------------------------------------------------------------------------------",
        "# 3. PROVIDER ROUTING PER TASK",
        "# ------------------------------------------------------------------------------",
        "# openai=OpenRouter  groq=Groq pool  gemini=Gemini pool  qwen=local SGLang",
        "",
        "VLM_PROVIDER=openai",
        "REASONING_PROVIDER=groq",
        "",
        f"PROVIDER_ENTITY_EXTRACTION={c['PROVIDER_ENTITY_EXTRACTION']}",
        f"PROVIDER_QUESTION_GENERATION={c['PROVIDER_QUESTION_GENERATION']}",
        f"PROVIDER_ENTITY_BINDING={c['PROVIDER_ENTITY_BINDING']}",
        f"PROVIDER_ENTITY_CLASSIFICATION={c['PROVIDER_ENTITY_CLASSIFICATION']}",
        f"PROVIDER_TOC_EXTRACTION={c['PROVIDER_TOC_EXTRACTION']}",
        f"PROVIDER_GAP_FILL={c['PROVIDER_GAP_FILL']}",
        f"PROVIDER_FACT_EXTRACTION={c['PROVIDER_FACT_EXTRACTION']}",
        f"PROVIDER_SEMANTIC_FALLBACK={c['PROVIDER_SEMANTIC_FALLBACK']}",
        "",
        "KEY_SLOT_ENTITY_EXTRACTION=",
        "KEY_SLOT_QUESTION_GENERATION=",
        "KEY_SLOT_ENTITY_BINDING=",
        "KEY_SLOT_ENTITY_CLASSIFICATION=",
        "KEY_SLOT_TOC_EXTRACTION=",
        "KEY_SLOT_GAP_FILL=",
        "KEY_SLOT_FACT_EXTRACTION=",
        "KEY_SLOT_SEMANTIC_FALLBACK=",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 4. OPENROUTER  (paid -- https://openrouter.ai/api/v1)",
        "# ------------------------------------------------------------------------------",
        "",
        "OPENAI_BASE_URL=https://openrouter.ai/api/v1",
        f"OPENAI_API_KEY={c['OPENROUTER_KEY']}",
        "",
        f"OPENAI_VISION_MODEL={c['OPENAI_VISION_MODEL']}",
        f"OPENAI_MODEL={c['OPENAI_MODEL']}",
        f"OPENAI_TIMEOUT={c['OPENAI_TIMEOUT']}",
        f"OPENAI_RPM={c['OPENAI_RPM']}",
        f"OPENAI_INCLUDE_REASONING={c['OPENAI_INCLUDE_REASONING']}",
        f"OPENAI_REASONING_EFFORT={c['OPENAI_REASONING_EFFORT']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 4b. PER-TASK MODEL OVERRIDES",
        "# ------------------------------------------------------------------------------",
        "# TASK_<TASK>_MODEL overrides the model for just that task.",
        "# Empty = use provider global default.",
        "# This is the ONLY correct place to name models -- not in Python code.",
        "",
        f"TASK_ENTITY_EXTRACTION_MODEL={c['TASK_ENTITY_EXTRACTION_MODEL']}",
        f"TASK_QUESTION_GENERATION_MODEL={c['TASK_QUESTION_GENERATION_MODEL']}",
        f"TASK_ENTITY_BINDING_MODEL={c['TASK_ENTITY_BINDING_MODEL']}",
        f"TASK_ENTITY_CLASSIFICATION_MODEL={c['TASK_ENTITY_CLASSIFICATION_MODEL']}",
        f"TASK_TOC_EXTRACTION_MODEL={c['TASK_TOC_EXTRACTION_MODEL']}",
        f"TASK_GAP_FILL_MODEL={c['TASK_GAP_FILL_MODEL']}",
        f"TASK_FACT_EXTRACTION_MODEL={c['TASK_FACT_EXTRACTION_MODEL']}",
        f"TASK_SEMANTIC_FALLBACK_MODEL={c['TASK_SEMANTIC_FALLBACK_MODEL']}",
        f"TASK_SEMANTIC_ENRICHMENT_MODEL={c['TASK_SEMANTIC_ENRICHMENT_MODEL']}",
        f"TASK_QUESTION_REPAIR_MODEL={c['TASK_QUESTION_REPAIR_MODEL']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 5. GROQ  (free tier -- https://api.groq.com/openai/v1)",
        "# ------------------------------------------------------------------------------",
        "",
        "GROQ_BASE_URL=https://api.groq.com/openai/v1",
        f"GROQ_MODEL={c['GROQ_MODEL']}",
        f"GROQ_VISION_MODEL={c['GROQ_VISION_MODEL']}",
        f"GROQ_RPM={c['GROQ_RPM']}",
        f"GROQ_MAX_TOKENS={c['GROQ_MAX_TOKENS']}",
        f"GROQ_TIMEOUT={c['GROQ_TIMEOUT']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 6. GEMINI  (free tier -- native Google API)",
        "# ------------------------------------------------------------------------------",
        "",
        f"GEMINI_MODEL={c['GEMINI_MODEL']}",
        f"GEMINI_VISION_MODEL={c['GEMINI_VISION_MODEL']}",
        f"GEMINI_ENRICHMENT={c['GEMINI_ENRICHMENT']}",
        f"GEMINI_RPM={c['GEMINI_RPM']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 7. LOCAL QWEN / SGLANG  (zero cost -- last-resort fallback)",
        "# ------------------------------------------------------------------------------",
        "",
        f"SGLANG_ENDPOINT={c['SGLANG_ENDPOINT']}",
        f"SGLANG_MODEL={c['SGLANG_MODEL']}",
        f"SGLANG_TIMEOUT={c['SGLANG_TIMEOUT']}",
        f"SGLANG_TEMPERATURE={c['SGLANG_TEMPERATURE']}",
        f"SGLANG_MAX_TOKENS={c['SGLANG_MAX_TOKENS']}",
        f"SGLANG_DECOMPOSED={c['SGLANG_DECOMPOSED']}",
        f"SGLANG_BACKEND={c['SGLANG_BACKEND']}",
        f"SGLANG_MEM_FRACTION={c['SGLANG_MEM_FRACTION']}",
        "",
        f"GUIDED_JSON={c['GUIDED_JSON']}",
        f"GUIDED_JSON_BACKEND={c['GUIDED_JSON_BACKEND']}",
        f"SELF_CONSISTENCY={c['SELF_CONSISTENCY']}",
        f"SELF_CONSISTENCY_THRESHOLD={c['SELF_CONSISTENCY_THRESHOLD']}",
        "",
        f"QWEN_ENTITY_MAX_OUTPUT={c['QWEN_ENTITY_MAX_OUTPUT']}",
        f"QWEN_QUESTION_MAX_OUTPUT={c['QWEN_QUESTION_MAX_OUTPUT']}",
        f"QWEN_PROMPT_MAX_CHARS={c['QWEN_PROMPT_MAX_CHARS']}",
        f"QWEN_IMAGE_MAX_DIM={c['QWEN_IMAGE_MAX_DIM']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 8. FALLBACK CHAINS",
        "# ------------------------------------------------------------------------------",
        "",
        f"FALLBACK_ENTITY_EXTRACTION={c['FALLBACK_ENTITY_EXTRACTION']}",
        f"FALLBACK_QUESTION_GENERATION={c['FALLBACK_QUESTION_GENERATION']}",
        f"FALLBACK_ENTITY_BINDING={c['FALLBACK_ENTITY_BINDING']}",
        f"FALLBACK_GAP_FILL={c['FALLBACK_GAP_FILL']}",
        f"FALLBACK_FACT_EXTRACTION={c['FALLBACK_FACT_EXTRACTION']}",
        f"FALLBACK_SEMANTIC_FALLBACK={c['FALLBACK_SEMANTIC_FALLBACK']}",
        f"FALLBACK_SEMANTIC_ENRICHMENT={c['FALLBACK_SEMANTIC_ENRICHMENT']}",
        "",
        f"ENABLE_TEXT_FALLBACK={c['ENABLE_TEXT_FALLBACK']}",
        f"ENABLE_VISION_FALLBACK={c['ENABLE_VISION_FALLBACK']}",
        f"FALLBACK_ON_PARSE_ERROR={c['FALLBACK_ON_PARSE_ERROR']}",
        f"FALLBACK_ON_RATE_LIMIT={c['FALLBACK_ON_RATE_LIMIT']}",
        f"FALLBACK_ON_CONTEXT_OVERFLOW={c['FALLBACK_ON_CONTEXT_OVERFLOW']}",
        f"FALLBACK_MAX_ATTEMPTS={c['FALLBACK_MAX_ATTEMPTS']}",
        f"VLM_FALLBACK_ORDER={c['VLM_FALLBACK_ORDER']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 9. TOKEN BUDGETS",
        "# ------------------------------------------------------------------------------",
        "# Temperatures: 0.0=JSON  0.1=near-det  0.15=balanced  0.2=reasoning",
        "",
        f"ENTITY_EXTRACTION_MAX_TOKENS={c['ENTITY_EXTRACTION_MAX_TOKENS']}",
        f"ENTITY_EXTRACTION_TEMPERATURE={c['ENTITY_EXTRACTION_TEMPERATURE']}",
        "",
        f"QUESTION_GENERATION_MAX_TOKENS={c['QUESTION_GENERATION_MAX_TOKENS']}",
        f"QUESTION_GENERATION_TEMPERATURE={c['QUESTION_GENERATION_TEMPERATURE']}",
        "",
        f"ENTITY_BINDING_MAX_TOKENS={c['ENTITY_BINDING_MAX_TOKENS']}",
        f"ENTITY_BINDING_TEMPERATURE={c['ENTITY_BINDING_TEMPERATURE']}",
        "",
        f"ENTITY_CLASSIFICATION_MAX_TOKENS={c['ENTITY_CLASSIFICATION_MAX_TOKENS']}",
        f"ENTITY_CLASSIFICATION_TEMPERATURE={c['ENTITY_CLASSIFICATION_TEMPERATURE']}",
        "",
        f"TOC_EXTRACTION_MAX_TOKENS={c['TOC_EXTRACTION_MAX_TOKENS']}",
        f"TOC_EXTRACTION_TEMPERATURE={c['TOC_EXTRACTION_TEMPERATURE']}",
        "",
        f"GAP_FILL_MAX_TOKENS={c['GAP_FILL_MAX_TOKENS']}",
        f"GAP_FILL_TEMPERATURE={c['GAP_FILL_TEMPERATURE']}",
        f"GAP_FILL_INCLUDE_REASONING={c['GAP_FILL_INCLUDE_REASONING']}",
        "",
        f"FACT_EXTRACTION_MAX_TOKENS={c['FACT_EXTRACTION_MAX_TOKENS']}",
        f"FACT_EXTRACTION_TEMPERATURE={c['FACT_EXTRACTION_TEMPERATURE']}",
        "",
        f"SEMANTIC_FALLBACK_MAX_TOKENS={c['SEMANTIC_FALLBACK_MAX_TOKENS']}",
        f"SEMANTIC_FALLBACK_TEMPERATURE={c['SEMANTIC_FALLBACK_TEMPERATURE']}",
        f"SEMANTIC_FALLBACK_INCLUDE_REASONING={c['SEMANTIC_FALLBACK_INCLUDE_REASONING']}",
        "",
        f"QUESTION_REPAIR_MAX_TOKENS={c['QUESTION_REPAIR_MAX_TOKENS']}",
        f"QUESTION_REPAIR_TEMPERATURE={c['QUESTION_REPAIR_TEMPERATURE']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 10. IMAGE SIZE (cost lever for OpenRouter vision)",
        "# ------------------------------------------------------------------------------",
        "",
        f"VLM_MAX_IMAGE_DIM={c['VLM_MAX_IMAGE_DIM']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 11. LOCAL SERVICES",
        "# ------------------------------------------------------------------------------",
        "",
        f"LAYOUTLM_ENDPOINT={c['LAYOUTLM_ENDPOINT']}",
        f"LAYOUTLM_TIMEOUT={c['LAYOUTLM_TIMEOUT']}",
        f"LAYOUTLM_PORT={c['LAYOUTLM_PORT']}",
        f"LAYOUTLM_MODEL_ID={c['LAYOUTLM_MODEL_ID']}",
        f"EMBEDDING_MODEL={c['EMBEDDING_MODEL']}",
        f"NEO4J_ENABLED={c['NEO4J_ENABLED']}",
        f"NEO4J_URI={c['NEO4J_URI']}",
        f"NEO4J_USER={c['NEO4J_USER']}",
        f"NEO4J_PASSWORD={c['NEO4J_PASSWORD']}",
        f"NEO4J_DATABASE={c['NEO4J_DATABASE']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 12. CACHE / CHECKPOINTING",
        "# ------------------------------------------------------------------------------",
        "",
        f"CHECKPOINT_ENABLED={c['CHECKPOINT_ENABLED']}",
        f"CHECKPOINT_MODE={c['CHECKPOINT_MODE']}",
        f"CHECKPOINT_PIPELINE_VERSION={c['CHECKPOINT_PIPELINE_VERSION']}",
        f"CHECKPOINT_STRICT_VERSION={c['CHECKPOINT_STRICT_VERSION']}",
        f"CHECKPOINT_NAMESPACE={c['CHECKPOINT_NAMESPACE']}",
        f"CHECKPOINT_DIR={c['CHECKPOINT_DIR']}",
        f"REDIS_URL={c['REDIS_URL']}",
        f"REDIS_CHECKPOINT_PREFIX={c['REDIS_CHECKPOINT_PREFIX']}",
        f"REDIS_CHECKPOINT_TTL_HOURS={c['REDIS_CHECKPOINT_TTL_HOURS']}",
        f"REDIS_CHECKPOINT_TTL_LLM_HOURS={c['REDIS_CHECKPOINT_TTL_LLM_HOURS']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 13. DATABASE & STORAGE",
        "# ------------------------------------------------------------------------------",
        "",
        f'DATABASE_URL="{c["DATABASE_URL"]}"',
        f"DB_NULL_POOL={c['DB_NULL_POOL']}",
        f"DB_POOL_SIZE={c['DB_POOL_SIZE']}",
        f"DB_POOL_MAX_OVERFLOW={c['DB_POOL_MAX_OVERFLOW']}",
        f"DB_POOL_TIMEOUT={c['DB_POOL_TIMEOUT']}",
        f"DB_POOL_RECYCLE={c['DB_POOL_RECYCLE']}",
        f"DB_CONNECT_TIMEOUT={c['DB_CONNECT_TIMEOUT']}",
        f"DB_ECHO_POOL={c['DB_ECHO_POOL']}",
        f"STORAGE_PROVIDER={c['STORAGE_PROVIDER']}",
        f"S3_BUCKET={c['S3_BUCKET']}",
        f"AWS_ACCESS_KEY_ID={c['AWS_ACCESS_KEY_ID']}",
        f"AWS_SECRET_ACCESS_KEY={c['AWS_SECRET_ACCESS_KEY']}",
        f"AWS_REGION={c['AWS_REGION']}",
        f"IMMUTABLE_VAULT_REQUIRED={c['IMMUTABLE_VAULT_REQUIRED']}",
        f"REPORT_STORAGE_PATH={c['REPORT_STORAGE_PATH']}",
        f"UPLOAD_STORAGE_PATH={c['UPLOAD_STORAGE_PATH']}",
        f"REPORT_TEMPLATE_DIR={c['REPORT_TEMPLATE_DIR']}",
        f"HUGGINGFACE_HUB_CACHE={c['HUGGINGFACE_HUB_CACHE']}",
        f"OUTPUT_DIR={c['OUTPUT_DIR']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 14. APP / AUTH",
        "# ------------------------------------------------------------------------------",
        "",
        f"SECRET_KEY={c['SECRET_KEY']}",
        f"APP_ENV={c['APP_ENV']}",
        f"AUTH_REQUIRED={c['AUTH_REQUIRED']}",
        f"DEV_AUTH_ENABLED={c['DEV_AUTH_ENABLED']}",
        f"DEV_TEST_EMAIL={c['DEV_TEST_EMAIL']}",
        f"DEV_TEST_PASSWORD={c['DEV_TEST_PASSWORD']}",
        f"DEV_TEST_OTP={c['DEV_TEST_OTP']}",
        f"DEV_TEST_FULL_NAME={c['DEV_TEST_FULL_NAME']}",
        f"DEV_TEST_OFFICER_ROLE={c['DEV_TEST_OFFICER_ROLE']}",
        f"CORS_ORIGINS={c['CORS_ORIGINS']}",
        f"JWT_ACCESS_MINUTES={c['JWT_ACCESS_MINUTES']}",
        f"JWT_REFRESH_DAYS={c['JWT_REFRESH_DAYS']}",
        f"OTP_LENGTH={c['OTP_LENGTH']}",
        f"OTP_TTL_MINUTES={c['OTP_TTL_MINUTES']}",
        f"OTP_MAX_ATTEMPTS={c['OTP_MAX_ATTEMPTS']}",
        f"NEXT_PUBLIC_API_URL={c['NEXT_PUBLIC_API_URL']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 15. EMAIL",
        "# ------------------------------------------------------------------------------",
        "",
        f"MAIL_INTERNAL_SECRET={c['MAIL_INTERNAL_SECRET']}",
        f"SMTP_HOST={c['SMTP_HOST']}",
        f"SMTP_PORT={c['SMTP_PORT']}",
        f"SMTP_USER={c['SMTP_USER']}",
        f"SMTP_PASS={c['SMTP_PASS']}",
        f"SMTP_FROM={c['SMTP_FROM']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 16. EXTRACTION QUALITY",
        "# ------------------------------------------------------------------------------",
        "",
        f"EXTRACTION_PIPELINE={c['EXTRACTION_PIPELINE']}",
        f"PDF_DPI={c['PDF_DPI']}",
        f"VLM_MAX_IMAGE_DIM={c['VLM_MAX_IMAGE_DIM']}",
        f"POPPLER_PATH={c['POPPLER_PATH']}",
        f"TESSERACT_CMD={c['TESSERACT_CMD']}",
        f"ENTITY_MIN_LENGTH={c['ENTITY_MIN_LENGTH']}",
        f"ENTITY_MAX_LENGTH={c['ENTITY_MAX_LENGTH']}",
        f"ENTITY_FUZZY_MATCH_THRESHOLD={c['ENTITY_FUZZY_MATCH_THRESHOLD']}",
        f"ENTITY_SIMILARITY_THRESHOLD={c['ENTITY_SIMILARITY_THRESHOLD']}",
        f"INFERENCE_CONFIDENCE_THRESHOLD={c['INFERENCE_CONFIDENCE_THRESHOLD']}",
        f"REVIEW_MIN_TOPICS={c['REVIEW_MIN_TOPICS']}",
        f"REVIEW_MIN_QUESTIONS={c['REVIEW_MIN_QUESTIONS']}",
        f"REVIEW_MIN_ENTITIES={c['REVIEW_MIN_ENTITIES']}",
        f"REVIEW_MIN_CONFIDENCE={c['REVIEW_MIN_CONFIDENCE']}",
        f"PIB_ENTITY_CAP={c['PIB_ENTITY_CAP']}",
        f"PIB_TABLE_CAP={c['PIB_TABLE_CAP']}",
        f"PIB_Q_PER_CHAPTER={c['PIB_Q_PER_CHAPTER']}",
        f"STAT_ENTITY_CAP={c['STAT_ENTITY_CAP']}",
        f"STAT_TABLE_CAP={c['STAT_TABLE_CAP']}",
        f"STAT_Q_PER_CHAPTER={c['STAT_Q_PER_CHAPTER']}",
        f"MAX_CHAPTERS_LOOP1={c['MAX_CHAPTERS_LOOP1']}",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 17. AGENT ROLES  (text agents -- use OPENAI_MODEL as fallback default)",
        "# ------------------------------------------------------------------------------",
        "",
        "DEFAULT_LLM_PROVIDER=openai",
        f"DEFAULT_LLM_MODEL={c['OPENAI_MODEL']}",
        "SCRIBE_PROVIDER=openai",
        f"SCRIBE_MODEL={c['OPENAI_MODEL']}",
        "INFERRER_PROVIDER=openai",
        f"INFERRER_MODEL={c['OPENAI_MODEL']}",
        "VERIFIER_PROVIDER=openai",
        f"VERIFIER_MODEL={c['OPENAI_MODEL']}",
        "PLANNER_PROVIDER=openai",
        f"PLANNER_MODEL={c['OPENAI_MODEL']}",
        "ENRICHER_PROVIDER=openai",
        f"ENRICHER_MODEL={c['OPENAI_MODEL']}",
        "GEMINI_RPM=60",
        "",
        "",
        "# ------------------------------------------------------------------------------",
        "# 18. OFFLINE / AIR-GAPPED",
        "# ------------------------------------------------------------------------------",
        "",
        f"GUIDED_JSON={c['GUIDED_JSON']}",
        f"GUIDED_JSON_BACKEND={c['GUIDED_JSON_BACKEND']}",
        f"SELF_CONSISTENCY={c['SELF_CONSISTENCY']}",
        f"SELF_CONSISTENCY_THRESHOLD={c['SELF_CONSISTENCY_THRESHOLD']}",
        f"LLM_DISABLED={c['LLM_DISABLED']}",
        f"EXTRACTION_EMIT_LEGACY={c['EXTRACTION_EMIT_LEGACY']}",
        f"LOG_LEVEL={c['LOG_LEVEL']}",
    ]
    return lines


if __name__ == "__main__":
    lines = _build_lines()
    content = "\n".join(lines) + "\n"

    bad = [(i, ch) for i, ch in enumerate(content) if ord(ch) > 127]
    if bad:
        print(f"ERROR: {len(bad)} non-ASCII chars. Aborting.", file=sys.stderr)
        for pos, ch in bad[:10]:
            print(f"  pos={pos} char={ch!r} U+{ord(ch):04X}", file=sys.stderr)
        sys.exit(1)

    TARGET.write_text(content, encoding="utf-8")
    rb = TARGET.read_text(encoding="utf-8")
    bad2 = [ch for ch in rb if ord(ch) > 127]
    print(f"Written: {len(rb.splitlines())} lines | Non-ASCII: {len(bad2)}")
    if bad2:
        print(f"STILL DIRTY: {set(bad2)}", file=sys.stderr)
        sys.exit(1)
    print("CLEAN. .env ready.")
    print()
    print("=" * 60)
    print("DEEP RESEARCH PROMPT (paste into your research agent):")
    print("=" * 60)
    print(DEEP_RESEARCH_PROMPT)
