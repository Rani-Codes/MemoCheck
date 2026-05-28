"""
Embedding + Hungarian matcher per ADR-002.

Flattens todos/events/reminders from both ground truth and agent output into
a single pool of items per side (notes excluded by design; see CLAUDE.md >
Metrics > "Not scored"). Pairs items 1-to-1 above a 0.8 cosine-similarity
threshold; unmatched items remain in their respective sides and feed
Detection (gt side) and Hallucination (agent side) at the scorer.

The string fed to the embedder is JUST the natural-language label
(`description` for TodoItem/Reminder, `title` for CalendarEvent). Type
tokens, dates, and people are NOT embedded -- ADR-002 explains why.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Union

import numpy as np
from scipy.optimize import linear_sum_assignment

from memocheck.agent.schema import ExtractedMemo
from memocheck.evals.schema import GroundTruthExtractedMemo

ExtractedMemoLike = Union[ExtractedMemo, GroundTruthExtractedMemo]
Embedder = Callable[[list[str]], np.ndarray]

DEFAULT_THRESHOLD = 0.8


@dataclass
class FlattenedItem:
    text: str
    type: str  # "todo" | "reminder" | "event"
    original: Any


@dataclass
class MatchResult:
    matched: list[tuple[FlattenedItem, FlattenedItem]] = field(default_factory=list)
    unmatched_gt: list[FlattenedItem] = field(default_factory=list)
    unmatched_agent: list[FlattenedItem] = field(default_factory=list)


def flatten(memo: ExtractedMemoLike) -> list[FlattenedItem]:
    items: list[FlattenedItem] = []
    for todo in memo.todos:
        items.append(FlattenedItem(text=todo.description, type="todo", original=todo))
    for event in memo.events:
        items.append(FlattenedItem(text=event.title, type="event", original=event))
    for reminder in memo.reminders:
        items.append(
            FlattenedItem(
                text=reminder.description, type="reminder", original=reminder
            )
        )
    return items


_default_embedder: Embedder | None = None


def _load_default_embedder() -> Embedder:
    global _default_embedder
    if _default_embedder is None:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

        def _embed(texts: list[str]) -> np.ndarray:
            return np.asarray(model.encode(texts), dtype=np.float32)

        _default_embedder = _embed
    return _default_embedder


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / np.linalg.norm(a, axis=1, keepdims=True)
    b_norm = b / np.linalg.norm(b, axis=1, keepdims=True)
    return np.asarray(a_norm @ b_norm.T)


def match(
    gt: GroundTruthExtractedMemo,
    agent: ExtractedMemo,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    embedder: Embedder | None = None,
) -> MatchResult:
    gt_items = flatten(gt)
    agent_items = flatten(agent)

    if not gt_items or not agent_items:
        return MatchResult(
            matched=[],
            unmatched_gt=list(gt_items),
            unmatched_agent=list(agent_items),
        )

    embed = embedder if embedder is not None else _load_default_embedder()
    gt_vecs = embed([item.text for item in gt_items])
    agent_vecs = embed([item.text for item in agent_items])

    sim = _cosine_similarity(gt_vecs, agent_vecs)

    # Hungarian maximizes assignment; scipy minimizes, so feed negative sim.
    # Cost padding for non-square matrices is handled by scipy automatically.
    row_ind, col_ind = linear_sum_assignment(-sim)

    matched: list[tuple[FlattenedItem, FlattenedItem]] = []
    matched_gt_idx: set[int] = set()
    matched_agent_idx: set[int] = set()
    for r, c in zip(row_ind, col_ind):
        if sim[r, c] >= threshold:
            matched.append((gt_items[r], agent_items[c]))
            matched_gt_idx.add(r)
            matched_agent_idx.add(c)

    unmatched_gt = [
        item for i, item in enumerate(gt_items) if i not in matched_gt_idx
    ]
    unmatched_agent = [
        item for i, item in enumerate(agent_items) if i not in matched_agent_idx
    ]
    return MatchResult(
        matched=matched,
        unmatched_gt=unmatched_gt,
        unmatched_agent=unmatched_agent,
    )
