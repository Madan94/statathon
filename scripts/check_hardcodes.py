"""Check for hardcoded model names in Python source files."""
import pathlib, sys

TARGETS = [
    "report_builder/llm_router.py",
    "report_builder/model_runtime/config.py",
]

# Model strings that must NOT appear in non-comment, non-docstring lines
BAD_MODELS = [
    "qwen3-vl-plus", "qwen3.5-flash", "qwen2.5-vl",
    "gpt-oss-120b", "gpt-4o-mini",
    "llama-3.3-70b", "llama-4-scout", "llama-4-maverick",
    "gemini-2.5", "gemini-1.5", "gemini-2.0",
    "deepseek-chat", "deepseek-r1",
]

ROOT = pathlib.Path(__file__).resolve().parent.parent
found = []

for fp in TARGETS:
    lines = (ROOT / fp).read_text(encoding="utf-8").splitlines()
    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Toggle docstring state
        if '"""' in stripped or "'''" in stripped:
            # Count quotes to determine open/close
            dq = stripped.count('"""')
            sq = stripped.count("'''")
            if dq % 2 == 1 or sq % 2 == 1:
                in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        # Skip pure comment lines
        if stripped.startswith("#"):
            continue
        for model in BAD_MODELS:
            if model.lower() in line.lower():
                found.append((fp, i, model, stripped[:100]))

if found:
    print(f"HARDCODED MODEL NAMES FOUND ({len(found)} occurrences):")
    for fp, ln, model, src in found:
        print(f"  {fp}:{ln}  [{model}]  {src}")
    sys.exit(1)
else:
    print("CLEAN: zero hardcoded model names in Python code.")
    print("All model names must be set via environment variables in scripts/write_clean_env.py")
