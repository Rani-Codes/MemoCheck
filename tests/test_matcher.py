from datetime import datetime

import numpy as np
import pytest

from memocheck.agent.schema import (
    CalendarEvent,
    ExtractedMemo,
    Reminder,
    TodoItem,
)
from memocheck.evals.matcher import flatten, match
from memocheck.evals.schema import (
    GroundTruthCalendarEvent,
    GroundTruthExtractedMemo,
    GroundTruthReminder,
    GroundTruthTodoItem,
)


def fake_embedder(lookup: dict[str, list[float]]):
    """Returns a deterministic embedder built from a text -> vector table."""

    def _embed(texts: list[str]) -> np.ndarray:
        return np.array([lookup[t] for t in texts], dtype=np.float32)

    return _embed


def test_flatten_preserves_type_and_back_pointer_across_all_three_types():
    todo = GroundTruthTodoItem(description="call the dentist")
    event = GroundTruthCalendarEvent(
        title="Coffee meeting with Sarah",
        start_datetime=datetime(2026, 6, 2, 10, 0),
    )
    reminder = GroundTruthReminder(description="mom and dad's anniversary")
    memo = GroundTruthExtractedMemo(
        todos=[todo],
        events=[event],
        reminders=[reminder],
        notes=["a stray observation that must NOT appear in the flattened pool"],
    )

    flat = flatten(memo)

    assert len(flat) == 3
    by_type = {item.type: item for item in flat}
    assert by_type["todo"].text == "call the dentist"
    assert by_type["todo"].original is todo
    assert by_type["event"].text == "Coffee meeting with Sarah"
    assert by_type["event"].original is event
    assert by_type["reminder"].text == "mom and dad's anniversary"
    assert by_type["reminder"].original is reminder


def test_flatten_excludes_notes():
    memo = GroundTruthExtractedMemo(notes=["not actionable"])
    assert flatten(memo) == []


def test_flatten_works_on_agent_extracted_memo_too():
    todo = TodoItem(description="Buy milk")
    event = CalendarEvent(title="Standup", start_datetime=datetime(2026, 5, 26, 9, 0))
    reminder = Reminder(description="passport expires next month")
    memo = ExtractedMemo(todos=[todo], events=[event], reminders=[reminder])

    flat = flatten(memo)
    types = sorted(item.type for item in flat)
    assert types == ["event", "reminder", "todo"]


def test_match_pairs_identical_label_above_threshold():
    gt = GroundTruthExtractedMemo(
        todos=[GroundTruthTodoItem(description="call the dentist")]
    )
    agent = ExtractedMemo(todos=[TodoItem(description="call the dentist")])
    embedder = fake_embedder({"call the dentist": [1.0, 0.0, 0.0]})

    result = match(gt, agent, embedder=embedder)

    assert len(result.matched) == 1
    gt_item, agent_item = result.matched[0]
    assert gt_item.text == "call the dentist"
    assert agent_item.text == "call the dentist"
    assert gt_item.original is gt.todos[0]
    assert agent_item.original is agent.todos[0]
    assert result.unmatched_gt == []
    assert result.unmatched_agent == []


def test_match_below_threshold_pair_stays_unmatched():
    gt = GroundTruthExtractedMemo(
        todos=[GroundTruthTodoItem(description="email landlord about heating")]
    )
    agent = ExtractedMemo(
        todos=[TodoItem(description="book Lake Tahoe campsite")]
    )
    embedder = fake_embedder(
        {
            "email landlord about heating": [1.0, 0.0, 0.0],
            "book Lake Tahoe campsite": [0.0, 1.0, 0.0],
        }
    )

    result = match(gt, agent, embedder=embedder)

    assert result.matched == []
    assert len(result.unmatched_gt) == 1
    assert result.unmatched_gt[0].text == "email landlord about heating"
    assert len(result.unmatched_agent) == 1
    assert result.unmatched_agent[0].text == "book Lake Tahoe campsite"


def test_match_borderline_at_exact_threshold_pairs():
    gt = GroundTruthExtractedMemo(
        todos=[GroundTruthTodoItem(description="x")]
    )
    agent = ExtractedMemo(todos=[TodoItem(description="y")])
    # vectors crafted so cosine sim == 0.8 exactly
    embedder = fake_embedder({"x": [1.0, 0.0], "y": [0.8, 0.6]})

    result = match(gt, agent, embedder=embedder)

    assert len(result.matched) == 1
    assert result.unmatched_gt == []
    assert result.unmatched_agent == []


@pytest.mark.slow
def test_real_sentence_transformers_model_pairs_paraphrases():
    """Integration test: with the real default embedder loaded, semantically
    equivalent labels pair above the 0.8 threshold and unrelated labels do
    not. Marked slow because it loads ~80MB on first run."""
    gt = GroundTruthExtractedMemo(
        todos=[
            GroundTruthTodoItem(description="call the dentist to schedule a cleaning"),
            GroundTruthTodoItem(description="email landlord about the heating"),
        ]
    )
    agent = ExtractedMemo(
        todos=[
            TodoItem(description="phone the dentist for an appointment"),
            TodoItem(description="message the landlord about heat issues"),
            TodoItem(description="completely unrelated thing: reorganize the garage"),
        ]
    )

    result = match(gt, agent)

    assert len(result.matched) == 2
    pairs = {(gt_i.text, agent_i.text) for gt_i, agent_i in result.matched}
    assert ("call the dentist to schedule a cleaning",
            "phone the dentist for an appointment") in pairs
    assert ("email landlord about the heating",
            "message the landlord about heat issues") in pairs
    assert [item.text for item in result.unmatched_agent] == [
        "completely unrelated thing: reorganize the garage"
    ]
    assert result.unmatched_gt == []


def test_embedder_receives_only_labels_no_dates_assignees_or_types():
    """ADR-002 invariant: the embedded string is JUST the natural-language
    label. No type tokens, no ISO dates, no assignees, no attendees should
    leak into the embedder input. This guards Tier 2/3 from being conflated
    into Tier 1."""
    gt = GroundTruthExtractedMemo(
        todos=[
            GroundTruthTodoItem(
                description="send proposal",
                due_date=datetime(2026, 6, 4, 23, 59),
                assignee="David",
            )
        ],
        events=[
            GroundTruthCalendarEvent(
                title="Team retrospective",
                start_datetime=datetime(2026, 5, 29, 14, 0),
                location="main conference room",
                attendees=["Alex", "Jordan", "Sam"],
            )
        ],
        reminders=[GroundTruthReminder(description="mom's birthday")],
    )
    agent = ExtractedMemo(
        todos=[TodoItem(description="send proposal")],
    )

    seen_inputs: list[list[str]] = []

    def spy_embedder(texts: list[str]) -> np.ndarray:
        seen_inputs.append(list(texts))
        return np.array([[1.0, 0.0]] * len(texts), dtype=np.float32)

    match(gt, agent, embedder=spy_embedder)

    flat_inputs = [t for batch in seen_inputs for t in batch]
    assert "send proposal" in flat_inputs
    assert "Team retrospective" in flat_inputs
    assert "mom's birthday" in flat_inputs

    forbidden = [
        "todo:",
        "event:",
        "reminder:",
        "David",
        "Alex",
        "Jordan",
        "Sam",
        "main conference room",
        "2026",
        "23:59",
        "14:00",
    ]
    for text in flat_inputs:
        for needle in forbidden:
            assert needle not in text, (
                f"embedder input {text!r} leaks forbidden token {needle!r}; "
                "Tier 2/3 fields must not be embedded (ADR-002)"
            )


def test_match_empty_gt_all_agent_items_unmatched():
    """When GT has zero action items, every agent item lands in
    unmatched_agent (drives Hallucination on a 'should-be-empty' case).
    The embedder must not even be invoked since there's nothing to pair."""
    gt = GroundTruthExtractedMemo()
    agent = ExtractedMemo(todos=[TodoItem(description="hallucinated todo")])

    def trap_embedder(_texts):
        raise AssertionError("embedder must not be called when one side is empty")

    result = match(gt, agent, embedder=trap_embedder)

    assert result.matched == []
    assert result.unmatched_gt == []
    assert [item.text for item in result.unmatched_agent] == ["hallucinated todo"]


def test_match_empty_agent_all_gt_items_unmatched():
    """When agent emits nothing, every GT item lands in unmatched_gt
    (drives Detection failure)."""
    gt = GroundTruthExtractedMemo(
        todos=[GroundTruthTodoItem(description="should have detected this")]
    )
    agent = ExtractedMemo()

    def trap_embedder(_texts):
        raise AssertionError("embedder must not be called when one side is empty")

    result = match(gt, agent, embedder=trap_embedder)

    assert result.matched == []
    assert [item.text for item in result.unmatched_gt] == ["should have detected this"]
    assert result.unmatched_agent == []


def test_match_both_sides_empty_returns_empty_result():
    gt = GroundTruthExtractedMemo()
    agent = ExtractedMemo()

    def trap_embedder(_texts):
        raise AssertionError("embedder must not be called when both sides empty")

    result = match(gt, agent, embedder=trap_embedder)

    assert result.matched == []
    assert result.unmatched_gt == []
    assert result.unmatched_agent == []


def test_match_unmatched_leftovers_go_to_larger_side_gt_heavier():
    """GT has 2 items, agent has 1. The matched pair consumes one of each;
    the remaining GT item goes to unmatched_gt (drives Detection failure)."""
    gt = GroundTruthExtractedMemo(
        todos=[
            GroundTruthTodoItem(description="A"),
            GroundTruthTodoItem(description="orphan_gt"),
        ]
    )
    agent = ExtractedMemo(todos=[TodoItem(description="A")])
    embedder = fake_embedder(
        {
            "A": [1.0, 0.0],
            "orphan_gt": [0.0, 1.0],
        }
    )

    result = match(gt, agent, embedder=embedder)

    assert len(result.matched) == 1
    assert result.matched[0][0].text == "A"
    assert [item.text for item in result.unmatched_gt] == ["orphan_gt"]
    assert result.unmatched_agent == []


def test_match_unmatched_leftovers_go_to_larger_side_agent_heavier():
    """Agent has 2 items, GT has 1. The remaining agent item goes to
    unmatched_agent (drives Hallucination)."""
    gt = GroundTruthExtractedMemo(
        todos=[GroundTruthTodoItem(description="A")]
    )
    agent = ExtractedMemo(
        todos=[
            TodoItem(description="A"),
            TodoItem(description="orphan_agent"),
        ]
    )
    embedder = fake_embedder(
        {
            "A": [1.0, 0.0],
            "orphan_agent": [0.0, 1.0],
        }
    )

    result = match(gt, agent, embedder=embedder)

    assert len(result.matched) == 1
    assert result.matched[0][0].text == "A"
    assert result.unmatched_gt == []
    assert [item.text for item in result.unmatched_agent] == ["orphan_agent"]


def test_match_assigns_optimal_cross_pairing_via_hungarian():
    """
    GT items A, B and agent items A', B' where the obvious pairing is the
    CROSS pairing (A <-> B', B <-> A'), not the direct one. A naive index-
    aligned impl would pair (A,A') + (B,B') which here are orthogonal and
    fall below threshold. Hungarian must pick the cross pairing.
    """
    gt = GroundTruthExtractedMemo(
        todos=[
            GroundTruthTodoItem(description="A"),
            GroundTruthTodoItem(description="B"),
        ]
    )
    agent = ExtractedMemo(
        todos=[
            TodoItem(description="A_prime"),
            TodoItem(description="B_prime"),
        ]
    )
    embedder = fake_embedder(
        {
            "A": [1.0, 0.0],
            "B": [0.0, 1.0],
            "A_prime": [0.0, 1.0],  # close to B, not A
            "B_prime": [1.0, 0.0],  # close to A, not B
        }
    )

    result = match(gt, agent, embedder=embedder)

    assert len(result.matched) == 2
    pairs = {(gt_i.text, agent_i.text) for gt_i, agent_i in result.matched}
    assert pairs == {("A", "B_prime"), ("B", "A_prime")}
    assert result.unmatched_gt == []
    assert result.unmatched_agent == []
