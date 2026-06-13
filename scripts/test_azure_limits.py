"""Test Azure GPT-5.2-chat and GPT-4o max output at various token budgets."""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import requests

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
headers = {"Content-Type": "application/json", "api-key": api_key}

BINDING_PROMPT = (
    "You are a statistical report binder. Given the entities and columns below, "
    "produce a JSON binding that maps each entity to its best-matching column.\n\n"
    "ENTITIES: [\"LFPR\", \"Worker Population Ratio\", \"Unemployment Rate\", "
    "\"Rural\", \"Urban\", \"Male\", \"Female\", \"2022-23\", \"2023-24\"]\n"
    "COLUMNS: [\"lfpr_usual\", \"wpr_usual\", \"ur_usual\", \"sector\", "
    "\"gender\", \"year\", \"state_name\", \"age_group\"]\n\n"
    "Return ONLY a JSON object with keys: bindings (array of {entity, column, confidence})."
)

GAP_FILL_PROMPT = (
    "You are a statistical gap-fill expert. Given the following partially extracted "
    "table from an Indian government labour force survey, fill in the missing values "
    "using contextual inference.\n\n"
    "Table (CSV):\n"
    "State,LFPR_Male,LFPR_Female,LFPR_Total,WPR_Male,WPR_Female,WPR_Total\n"
    "Andhra Pradesh,73.2,38.1,,71.4,,54.2\n"
    "Bihar,68.5,,35.1,66.2,4.8,\n"
    "Gujarat,,27.3,55.8,,25.9,53.8\n"
    "Karnataka,74.1,33.6,,72.5,,53.4\n"
    "Maharashtra,,28.4,56.2,,27.1,54.8\n\n"
    "Output: complete the table as valid CSV with all cells filled. "
    "Then provide a JSON explanation array with {state, field, inferred_value, method, confidence}."
)

TOC_PROMPT = (
    "Extract the Table of Contents from this government document text. "
    "Return a JSON array of {heading, level, page_number, section_id}.\n\n"
    "TEXT:\n"
    "PERIODIC LABOUR FORCE SURVEY ANNUAL REPORT 2023-24\n"
    "Chapter 1: Introduction and Methodology ... 1\n"
    "  1.1 Background ... 2\n  1.2 Sample Design ... 5\n  1.3 Survey Period ... 8\n"
    "Chapter 2: Key Employment Indicators ... 12\n"
    "  2.1 Labour Force Participation Rate ... 13\n  2.2 Worker Population Ratio ... 18\n"
    "  2.3 Unemployment Rate ... 23\n  2.4 Activity Status Classification ... 28\n"
    "Chapter 3: Sectoral Distribution ... 35\n"
    "  3.1 Agriculture ... 36\n  3.2 Manufacturing ... 41\n  3.3 Services ... 46\n"
    "Chapter 4: State-Level Analysis ... 52\n"
    "  4.1 Major States ... 53\n  4.2 Union Territories ... 68\n"
    "Chapter 5: Gender Analysis ... 74\n"
    "  5.1 Female Labour Force Participation ... 75\n  5.2 Gender Wage Gap ... 82\n"
    "Appendix A: Statistical Tables ... 89\nAppendix B: Methodology Notes ... 95\n"
    "Appendix C: Questionnaire ... 101\n"
)


def test_deployment(deploy_name, prompts, token_values, is_reasoning=False):
    url = f"{endpoint}/openai/deployments/{deploy_name}/chat/completions?api-version={api_version}"
    print(f"\n{'='*70}")
    print(f"  DEPLOYMENT: {deploy_name} ({'reasoning model' if is_reasoning else 'standard model'})")
    print(f"{'='*70}")

    for prompt_name, prompt_text in prompts:
        print(f"\n  --- Task: {prompt_name} (prompt={len(prompt_text)} chars) ---")
        for max_tok in token_values:
            payload = {"messages": [{"role": "user", "content": prompt_text}]}
            if is_reasoning:
                payload["max_completion_tokens"] = max_tok
            else:
                payload["max_tokens"] = max_tok
                payload["temperature"] = 0.1

            t0 = time.time()
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=90)
            except Exception as e:
                print(f"    max_tok={max_tok:>6} | ERROR: {e}")
                continue
            elapsed = time.time() - t0

            if r.status_code == 200:
                data = r.json()
                usage = data.get("usage", {})
                choice = data["choices"][0]
                content = choice["message"].get("content", "") or ""
                finish = choice.get("finish_reason", "?")
                prompt_tok = usage.get("prompt_tokens", 0)
                output_tok = usage.get("completion_tokens", 0)
                reasoning_tok = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
                visible_tok = output_tok - reasoning_tok

                print(
                    f"    max_tok={max_tok:>6} | out={output_tok:>5} "
                    f"(reason={reasoning_tok:>4}, visible={visible_tok:>4}) | "
                    f"finish={finish:<6} | {elapsed:.1f}s | content={len(content)} chars"
                )
                if finish == "length":
                    print(f"      ** TRUNCATED — model ran out of tokens")
            else:
                err = r.text[:150]
                print(f"    max_tok={max_tok:>6} | HTTP {r.status_code}: {err}")

            time.sleep(0.3)


if __name__ == "__main__":
    text_prompts = [
        ("entity_binding", BINDING_PROMPT),
        ("gap_fill", GAP_FILL_PROMPT),
        ("toc_extraction", TOC_PROMPT),
    ]

    # gpt-5.2-chat: reasoning model (uses max_completion_tokens, no temperature)
    test_deployment(
        "gpt-5.2-chat",
        text_prompts,
        [512, 1024, 2048, 4096, 8192, 16000],
        is_reasoning=True,
    )

    # gpt-4o-graphiti-2: standard model (uses max_tokens + temperature)
    test_deployment(
        "gpt-4o-graphiti-2",
        text_prompts,
        [512, 1024, 2048, 4096, 8192, 16000],
        is_reasoning=False,
    )
