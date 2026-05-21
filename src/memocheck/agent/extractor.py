from __future__ import annotations

import re
import time
from typing import Union

import litellm
from pydantic import ValidationError

from memocheck.agent.schema import ExtractedMemo, ExtractionError


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
) -> tuple[Union[ExtractedMemo, ExtractionError], bool, int, float]:
    messages = [
        {
            "role": "system",
            "content": system_prompt.replace("{current_date}", memo_recorded_at),
        },
        {"role": "user", "content": transcript},
    ]

    start = time.monotonic()
    total_cost = 0.0

    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            temperature=0,
        )
        total_cost += litellm.completion_cost(response, model=model)

        try:
            result = ExtractedMemo.model_validate_json(
                _strip_markdown(response.choices[0].message.content)
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            return result, True, latency_ms, total_cost

        except ValidationError as first_error:
            cleaned = _strip_markdown(response.choices[0].message.content)
            messages.append({"role": "assistant", "content": cleaned})
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
            total_cost += litellm.completion_cost(retry_response)

            try:
                result = ExtractedMemo.model_validate_json(
                    _strip_markdown(retry_response.choices[0].message.content)
                )
                latency_ms = int((time.monotonic() - start) * 1000)
                return result, False, latency_ms, total_cost

            except ValidationError as second_error:
                latency_ms = int((time.monotonic() - start) * 1000)
                return (
                    ExtractionError(
                        error=str(second_error),
                        raw_response=retry_response.choices[0].message.content,
                    ),
                    False,
                    latency_ms,
                    total_cost,
                )

    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ExtractionError(error=str(exc), raw_response=""), False, latency_ms, 0.0
