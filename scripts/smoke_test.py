"""
Run: python scripts/smoke_test.py
Requires all four API keys set in .env
"""
import os
from dotenv import load_dotenv
from memocheck.agent.extractor import extract
from memocheck.agent.prompts.v0 import SYSTEM_PROMPT
from memocheck.agent.schema import ExtractedMemo

load_dotenv()

TRANSCRIPT = "Remind me to pick up dry cleaning on Thursday and call mom this weekend."
RECORDED_AT = "2026-05-09T10:00:00Z"

PROVIDERS = [
    "anthropic/claude-haiku-4-5",
    "openai/gpt-4.1-mini",
    "gemini/gemini-2.5-flash",
    "groq/llama-3.3-70b-versatile",
]

for model in PROVIDERS:
    result, schema_valid, latency_ms, cost_usd = extract(
        transcript=TRANSCRIPT,
        memo_recorded_at=RECORDED_AT,
        model=model,
        system_prompt=SYSTEM_PROMPT,
    )
    status = "OK" if isinstance(result, ExtractedMemo) else "FAIL"
    print(f"{model}: {status} | schema_valid={schema_valid} | {latency_ms}ms | ${cost_usd:.6f}")
    if isinstance(result, ExtractedMemo):
        print(f"  reminders: {[r.description for r in result.reminders]}")
