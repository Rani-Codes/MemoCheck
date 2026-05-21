from __future__ import annotations

import re
import time

import litellm
from pydantic import ValidationError

from memocheck.agent.schema import (
    ExtractedMemo,
    ExtractionError,
    ExtractionResult,
)


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
        response = litellm.completion(
            model=model,
            messages=messages,
            temperature=0,
        )
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

            retry_response = litellm.completion(
                model=model,
                messages=messages,
                temperature=0,
            )
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
