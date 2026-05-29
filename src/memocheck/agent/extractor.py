from __future__ import annotations

import re
import time
from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from pydantic import ValidationError

from memocheck.agent.schema import (
    ExtractedMemo,
    ExtractionError,
    ExtractionResult,
)

# Transient API failures worth retrying with backoff (notably free-tier rate
# limits like Groq's 12k tokens/min). Non-retryable errors (auth, bad request)
# fall through to the ExtractionError path immediately.
_RETRYABLE_ERRORS = (
    RateLimitError,
    APIConnectionError,
    Timeout,
    InternalServerError,
    ServiceUnavailableError,
)


def _completion_with_backoff(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_retries: int = 6,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> Any:
    """`litellm.completion` with exponential backoff on transient/rate-limit errors.

    The backoff budget (~90s over the default 6 retries) spans more than a
    minute, long enough for a per-minute token cap to reset. A request that still
    fails is raised, becomes an ExtractionError, and is resumed later by the
    runner. `timeout` also prevents an indefinite hang on a dead socket (e.g.
    after the laptop sleeps mid-run).
    """
    delay = base_delay
    for attempt in range(max_retries + 1):
        try:
            return litellm.completion(
                model=model, messages=messages, temperature=0, timeout=60
            )
        except _RETRYABLE_ERRORS:
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, max_delay)


def _strip_markdown(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


def extract(
    transcript: str,
    memo_recorded_at: str,
    model: str,
    system_prompt: str,
) -> ExtractionResult:
    messages = [
        {
            "role": "system",
            "content": system_prompt.replace("{current_date}", memo_recorded_at),
        },
        {"role": "user", "content": transcript},
    ]

    start = time.monotonic()
    total_cost = 0.0
    raw_response = ""

    try:
        response = _completion_with_backoff(model, messages)
        total_cost += litellm.completion_cost(response, model=model)
        raw_response = response.choices[0].message.content

        try:
            result = ExtractedMemo.model_validate_json(_strip_markdown(raw_response))
            latency_ms = int((time.monotonic() - start) * 1000)
            return ExtractionResult(
                output=result,
                schema_valid=True,
                latency_ms=latency_ms,
                cost_usd=total_cost,
                raw_response=raw_response,
            )

        except ValidationError as first_error:
            messages.append(
                {"role": "assistant", "content": _strip_markdown(raw_response)}
            )
            error_msg = (
                f"Your response failed validation: {first_error}. "
                "Return raw JSON only, no markdown, no extra text."
            )
            messages.append({"role": "user", "content": error_msg})

            retry_response = _completion_with_backoff(model, messages)
            total_cost += litellm.completion_cost(retry_response, model=model)
            raw_response = retry_response.choices[0].message.content

            try:
                result = ExtractedMemo.model_validate_json(
                    _strip_markdown(raw_response)
                )
                latency_ms = int((time.monotonic() - start) * 1000)
                return ExtractionResult(
                    output=result,
                    schema_valid=False,
                    latency_ms=latency_ms,
                    cost_usd=total_cost,
                    raw_response=raw_response,
                )

            except ValidationError as second_error:
                latency_ms = int((time.monotonic() - start) * 1000)
                return ExtractionResult(
                    output=ExtractionError(error=str(second_error)),
                    schema_valid=False,
                    latency_ms=latency_ms,
                    cost_usd=total_cost,
                    raw_response=raw_response,
                )

    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ExtractionResult(
            output=ExtractionError(error=f"{type(exc).__name__}: {exc}"),
            schema_valid=False,
            latency_ms=latency_ms,
            cost_usd=total_cost,
            raw_response=raw_response,
        )
