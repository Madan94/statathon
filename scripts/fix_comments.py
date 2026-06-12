"""Fix hardcoded model name comments in llm_router.py."""
import pathlib

p = pathlib.Path("report_builder/llm_router.py")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

for i, line in enumerate(lines):
    if "Qwen3-VL-Plus" in line or "Qwen3.5-Flash" in line:
        lines[i] = '    "openai": 32500,  # OpenRouter: varies by model; conservative cap\n'
        print(f"Fixed line {i+1}: openai cap comment")
    elif "gpt-oss-120b supports" in line:
        lines[i] = '    "groq":   16000,  # Groq: most models support 32K+; cap at 16K\n'
        print(f"Fixed line {i+1}: groq cap comment")
    elif "3B model" in line and ("vision-only fallback" in line or "tight context" in line):
        lines[i] = '    "qwen":   500,    # local 3B model -- last-resort vision fallback\n'
        print(f"Fixed line {i+1}: qwen cap comment")

p.write_text("".join(lines), encoding="utf-8")
print("Done.")
