"""LLM judge for the matcher's ambiguous band (ADR-002 escalation).

The matcher auto-accepts pairs at/above the ceiling (0.80) and auto-rejects
below the floor (0.50). In between, the surface cosine is an unreliable signal,
so a non-SUT LLM (default Claude Sonnet 4.6) decides whether two labels name the
same underlying action item. See `docs/v0-matcher-validation.md` for why a
judged band is used instead of a single re-tuned threshold.

Determinism: the judge runs at temperature 0 and every verdict is cached on
`(model, gt_label, agent_label)`, so re-scores are stable and never re-pay for a
pair already seen. Pass a persisted `JudgeCache` to survive across processes.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from memocheck.evals.matcher import Judge

DEFAULT_JUDGE_MODEL = "anthropic/claude-sonnet-4-6"

CompleteFn = Callable[..., Any]

_SYSTEM_PROMPT = (
    "You score an information-extraction benchmark. You are given two short "
    "labels: one from the hand-labeled ground truth and one produced by an "
    "agent, both extracted from the same voice memo. Decide whether they refer "
    "to the SAME underlying action item (same task, event, or reminder), even "
    "if the wording, length, or detail differs. Differences in date, time, "
    "assignee, or phrasing do NOT make them different items; those are scored "
    "separately. Two genuinely different actions (for example 'review the "
    "proposal' vs 'send the proposal') are NOT the same item. Respond with JSON "
    'only: {"same_item": <true|false>, "reason": "<brief>"}.'
)


class JudgeVerdict(BaseModel):
    same_item: bool
    reason: str = ""


class JudgeCache(MutableMapping[str, bool]):
    """A dict-like verdict cache persisted to a JSON file (loaded on init,
    written on each set). Keys are opaque strings; values are bool verdicts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[str, bool] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def __getitem__(self, key: str) -> bool:
        return self._data[key]

    def __setitem__(self, key: str, value: bool) -> None:
        self._data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True))

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _strip_markdown(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
    if content.endswith("```"):
        content = content.rsplit("```", 1)[0]
    return content.strip()


def make_judge(
    transcript: str = "",
    *,
    model: str | None = None,
    complete: CompleteFn | None = None,
    cache: MutableMapping[str, bool] | None = None,
) -> Judge:
    """Build a `Judge` bound to one transcript's context.

    `complete` defaults to `litellm.completion` and is injectable so tests never
    hit the network. `cache` defaults to an in-process dict; pass a `JudgeCache`
    for cross-process persistence.
    """
    resolved_model = model or os.environ.get("MATCHER_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
    if complete is None:
        import litellm

        complete = litellm.completion
    if cache is None:
        cache = {}

    def _judge(gt_text: str, agent_text: str) -> bool:
        key = f"{resolved_model}\x1f{gt_text}\x1f{agent_text}"
        if key in cache:
            return cache[key]
        user = (
            f"Voice memo transcript:\n{transcript}\n\n"
            f"Ground-truth label: {gt_text!r}\n"
            f"Agent label: {agent_text!r}\n\n"
            "Are these the same underlying action item?"
        )
        response = complete(
            model=resolved_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content
        verdict = JudgeVerdict.model_validate_json(_strip_markdown(content)).same_item
        cache[key] = verdict
        return verdict

    return _judge
