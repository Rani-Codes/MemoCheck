"""
Deterministic scorer per ADR-001.

Reads a `MatchResult` from the matcher and produces a per-case `CaseScore`
covering all metrics derived from matching. Schema Adherence is tracked
separately on `ExtractionResult.schema_valid` by the runner.

Timezone handling (ADR-003): ground truth is authored tz-aware in the memo's
local offset, while the agent emits naive local wall-clock datetimes (see
`agent/prompts/v0.py`). Before any date comparison we localize naive values to
the memo's timezone (`default_tz`, threaded in from `memo_recorded_at`) so both
sides become tz-aware. Comparing tz-aware datetimes is by true instant -- i.e.
the comparison happens in UTC -- which also handles a model that emits an
explicit offset or trailing `Z`. The agent never reasons about UTC; the
conversion lives entirely here. When `default_tz` is None (naive-only unit
tests) localization is a no-op, preserving naive-vs-naive comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional, Union

from memocheck.evals.matcher import FlattenedItem, MatchResult
from memocheck.evals.schema import TimeWindow

DateValue = Union[date, datetime, None]
TOLERANCE_SECONDS = 60


@dataclass
class CaseScore:
    detection_matched: int = 0
    detection_relevant: int = 0  # matched + unmatched_gt
    hallucination_unmatched: int = 0
    hallucination_relevant: int = 0  # matched + unmatched_agent
    type_correct: int = 0
    type_pair_count: int = 0  # len(matched)
    date_correct: int = 0
    date_pair_count: int = 0  # type-matched pairs only
    attribution_correct: int = 0
    attribution_pair_count: int = 0  # type-matched todo/event pairs only
    negation_correct: int = 0
    negation_pair_count: int = 0  # ALL matched pairs (type-agnostic)
    negation_false_positive: int = 0  # agent=True, gt=False
    negation_false_negative: int = 0  # agent=False, gt=True


def score_case(
    match_result: MatchResult, *, default_tz: tzinfo | None = None
) -> CaseScore:
    """Score one matched case.

    `default_tz` is the memo's local timezone (from `memo_recorded_at`). Naive
    datetimes on either side are localized to it before date comparison (see the
    module docstring). The real runner always passes it; it defaults to None so
    naive-only unit tests keep working unchanged.
    """
    matched = match_result.matched
    unmatched_gt = match_result.unmatched_gt
    unmatched_agent = match_result.unmatched_agent

    type_correct = 0
    date_correct = 0
    date_pair_count = 0
    attribution_correct = 0
    attribution_pair_count = 0
    negation_correct = 0
    negation_fp = 0
    negation_fn = 0
    for gt, ag in matched:
        type_match = gt.type == ag.type
        if type_match:
            type_correct += 1
            date_pair_count += 1
            if _date_passes(gt, ag, default_tz):
                date_correct += 1
            if gt.type in ("todo", "event"):
                attribution_pair_count += 1
                if _attribution_passes(gt, ag):
                    attribution_correct += 1
        if gt.original.negated == ag.original.negated:
            negation_correct += 1
        elif ag.original.negated and not gt.original.negated:
            negation_fp += 1
        else:
            negation_fn += 1

    return CaseScore(
        detection_matched=len(matched),
        detection_relevant=len(matched) + len(unmatched_gt),
        hallucination_unmatched=len(unmatched_agent),
        hallucination_relevant=len(matched) + len(unmatched_agent),
        type_correct=type_correct,
        type_pair_count=len(matched),
        date_correct=date_correct,
        date_pair_count=date_pair_count,
        attribution_correct=attribution_correct,
        attribution_pair_count=attribution_pair_count,
        negation_correct=negation_correct,
        negation_pair_count=len(matched),
        negation_false_positive=negation_fp,
        negation_false_negative=negation_fn,
    )


def _date_passes(
    gt: FlattenedItem, ag: FlattenedItem, default_tz: tzinfo | None
) -> bool:
    gt_window = _gt_date_window(gt, default_tz)
    ag_window = _agent_date_window(ag, default_tz)
    if gt_window is None and ag_window is None:
        return True
    if gt_window is None or ag_window is None:
        return False
    return _windows_overlap(gt_window, ag_window)


def _gt_date_window(
    item: FlattenedItem, default_tz: tzinfo | None
) -> Optional[TimeWindow]:
    orig = item.original
    # Locals annotated because FlattenedItem.original is Any (matcher type tag).
    if item.type == "todo":
        win: Optional[TimeWindow] = orig.due_date_window
        if win is not None:
            return _localize_window(win, default_tz)
        return _value_to_window(orig.due_date, tolerance=False, default_tz=default_tz)
    if item.type == "reminder":
        win = orig.remind_at_window
        if win is not None:
            return _localize_window(win, default_tz)
        return _value_to_window(orig.remind_at, tolerance=False, default_tz=default_tz)
    if item.type == "event":
        win = orig.start_datetime_window
        if win is not None:
            return _localize_window(win, default_tz)
        return _value_to_window(
            orig.start_datetime, tolerance=False, default_tz=default_tz
        )
    raise ValueError(f"unknown item type {item.type!r}")


def _agent_date_window(
    item: FlattenedItem, default_tz: tzinfo | None
) -> Optional[TimeWindow]:
    orig = item.original
    if item.type == "todo":
        val = orig.due_date
    elif item.type == "reminder":
        val = orig.remind_at
    elif item.type == "event":
        val = orig.start_datetime
    else:
        raise ValueError(f"unknown item type {item.type!r}")
    return _value_to_window(val, tolerance=True, default_tz=default_tz)


def _localize(dt: datetime, default_tz: tzinfo | None) -> datetime:
    """Attach `default_tz` to a naive datetime; leave aware datetimes untouched.

    ADR-003 guarantees every datetime in a case shares the memo's offset, so a
    naive agent value is by construction in `default_tz`. No-op when default_tz
    is None.
    """
    if dt.tzinfo is None and default_tz is not None:
        return dt.replace(tzinfo=default_tz)
    return dt


def _localize_window(win: TimeWindow, default_tz: tzinfo | None) -> TimeWindow:
    return TimeWindow(
        start=_localize(win.start, default_tz) if win.start is not None else None,
        end=_localize(win.end, default_tz) if win.end is not None else None,
    )


def _value_to_window(
    val: DateValue, *, tolerance: bool, default_tz: tzinfo | None
) -> Optional[TimeWindow]:
    if val is None:
        return None
    # NOTE: isinstance(datetime) must be checked first; datetime is a subclass of date.
    if isinstance(val, datetime):
        dt = _localize(val, default_tz)
        if tolerance:
            slop = timedelta(seconds=TOLERANCE_SECONDS)
            return TimeWindow(start=dt - slop, end=dt + slop)
        return TimeWindow(start=dt, end=dt)
    if isinstance(val, date):
        return TimeWindow(
            start=_localize(datetime.combine(val, time.min), default_tz),
            end=_localize(datetime.combine(val, time.max), default_tz),
        )
    raise TypeError(f"unsupported date value type {type(val).__name__}")


def _attribution_passes(gt: FlattenedItem, ag: FlattenedItem) -> bool:
    if gt.type == "todo":
        return _normalize_assignee(gt.original.assignee) == _normalize_assignee(
            ag.original.assignee
        )
    if gt.type == "event":
        return _normalize_attendees(gt.original.attendees) == _normalize_attendees(
            ag.original.attendees
        )
    raise ValueError(f"attribution undefined for type {gt.type!r}")


def _normalize_assignee(val: Optional[str]) -> str:
    if val is None:
        return ""
    return val.strip().casefold()


def _normalize_attendees(vals: Optional[list[str]]) -> frozenset[str]:
    if vals is None:
        return frozenset()
    return frozenset(v.strip().casefold() for v in vals)


def _windows_overlap(a: TimeWindow, b: TimeWindow) -> bool:
    if a.start is not None and b.end is not None and a.start > b.end:
        return False
    if b.start is not None and a.end is not None and b.start > a.end:
        return False
    return True
