from __future__ import annotations

import time
from typing import Union

import litellm
from pydantic import ValidationError

from memocheck.agent.schema import ExtractedMemo, ExtractionError


def extract(
    transcript: str,
    memo_recorded_at: str,
    model: str,
    system_prompt: str,
) -> tuple[Union[ExtractedMemo, ExtractionError], bool, int, float]:
    messages = [
        {
            "role": "system",
            "content": system_prompt.format(current_date=memo_recorded_at),
        },
        {"role": "user", "content": transcript},
    ]

    start = time.monotonic()
    total_cost = 0.0

    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            response_format=ExtractedMemo,
            temperature=0,
        )
        total_cost += litellm.completion_cost(response)

        try:
            result = ExtractedMemo.model_validate_json(
                response.choices[0].message.content
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            return result, True, latency_ms, total_cost

        except ValidationError as first_error:
            messages.append(
                {"role": "assistant", "content": response.choices[0].message.content}
            )
            error_msg = (
                f"Your response failed validation: {first_error}. "
                "Please fix it and return valid JSON matching the schema."
            )
            messages.append({"role": "user", "content": error_msg})

            retry_response = litellm.completion(
                model=model,
                messages=messages,
                response_format=ExtractedMemo,
                temperature=0,
            )
            total_cost += litellm.completion_cost(retry_response)

            try:
                result = ExtractedMemo.model_validate_json(
                    retry_response.choices[0].message.content
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
