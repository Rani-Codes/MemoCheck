from datetime import date, datetime

from memocheck.agent.schema import (
    CalendarEvent,
    Reminder,
    TodoItem,
)
from memocheck.evals.matcher import FlattenedItem, MatchResult
from memocheck.evals.schema import (
    GroundTruthCalendarEvent,
    GroundTruthReminder,
    GroundTruthTodoItem,
    TimeWindow,
)
from memocheck.evals.scorer import score_case


def _gt_todo_item(description="x", **kwargs):
    return FlattenedItem(
        text=description,
        type="todo",
        original=GroundTruthTodoItem(description=description, **kwargs),
    )


def _agent_todo_item(description="x", **kwargs):
    return FlattenedItem(
        text=description,
        type="todo",
        original=TodoItem(description=description, **kwargs),
    )


def _gt_event_item(title="x", start_datetime=None, **kwargs):
    if start_datetime is None and "start_datetime_window" not in kwargs:
        start_datetime = datetime(2026, 1, 1, 9, 0)
    return FlattenedItem(
        text=title,
        type="event",
        original=GroundTruthCalendarEvent(
            title=title, start_datetime=start_datetime, **kwargs
        ),
    )


def _agent_event_item(title="x", start_datetime=None, **kwargs):
    if start_datetime is None:
        start_datetime = datetime(2026, 1, 1, 9, 0)
    return FlattenedItem(
        text=title,
        type="event",
        original=CalendarEvent(title=title, start_datetime=start_datetime, **kwargs),
    )


def _gt_reminder_item(description="x", **kwargs):
    return FlattenedItem(
        text=description,
        type="reminder",
        original=GroundTruthReminder(description=description, **kwargs),
    )


def _agent_reminder_item(description="x", **kwargs):
    return FlattenedItem(
        text=description,
        type="reminder",
        original=Reminder(description=description, **kwargs),
    )


def test_detection_rate_all_matched():
    """1 GT item, 1 agent item, matched -> detection 1/1."""
    gt = _gt_todo_item("call dentist")
    ag = _agent_todo_item("call dentist")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.detection_matched == 1
    assert score.detection_relevant == 1


def test_detection_rate_missed_item():
    """2 GT items, 1 matched, 1 missed -> detection 1/2."""
    gt_matched = _gt_todo_item("A")
    gt_missed = _gt_todo_item("B")
    ag = _agent_todo_item("A")
    match_result = MatchResult(
        matched=[(gt_matched, ag)],
        unmatched_gt=[gt_missed],
        unmatched_agent=[],
    )

    score = score_case(match_result)

    assert score.detection_matched == 1
    assert score.detection_relevant == 2


def test_detection_rate_undefined_when_gt_empty():
    """Empty GT side -> detection denominator is 0; aggregator excludes."""
    ag = _agent_todo_item("hallucinated")
    match_result = MatchResult(matched=[], unmatched_gt=[], unmatched_agent=[ag])

    score = score_case(match_result)

    assert score.detection_matched == 0
    assert score.detection_relevant == 0


def test_hallucination_rate_phantom_agent_item():
    """1 matched, 1 hallucinated -> hallucination 1/2."""
    gt = _gt_todo_item("real")
    ag_matched = _agent_todo_item("real")
    ag_phantom = _agent_todo_item("phantom")
    match_result = MatchResult(
        matched=[(gt, ag_matched)],
        unmatched_gt=[],
        unmatched_agent=[ag_phantom],
    )

    score = score_case(match_result)

    assert score.hallucination_unmatched == 1
    assert score.hallucination_relevant == 2


def test_hallucination_rate_undefined_when_agent_empty():
    """Empty agent side -> hallucination denominator is 0."""
    gt = _gt_todo_item("undetected")
    match_result = MatchResult(matched=[], unmatched_gt=[gt], unmatched_agent=[])

    score = score_case(match_result)

    assert score.hallucination_unmatched == 0
    assert score.hallucination_relevant == 0


def test_type_accuracy_same_type_matches():
    """Matched pair, both todo -> type accuracy 1/1."""
    gt = _gt_todo_item("call dentist")
    ag = _agent_todo_item("call dentist")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.type_correct == 1
    assert score.type_pair_count == 1


def test_type_accuracy_mismatch():
    """Matched pair, gt=reminder vs agent=todo -> type accuracy 0/1."""
    gt = _gt_reminder_item("mom's birthday")
    ag = _agent_todo_item("mom's birthday")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.type_correct == 0
    assert score.type_pair_count == 1


def test_type_accuracy_only_counts_matched_pairs():
    """Unmatched items do not enter the Tier 2 denominator."""
    gt_unmatched = _gt_todo_item("unmatched")
    ag_unmatched = _agent_todo_item("phantom")
    match_result = MatchResult(
        matched=[],
        unmatched_gt=[gt_unmatched],
        unmatched_agent=[ag_unmatched],
    )

    score = score_case(match_result)

    assert score.type_correct == 0
    assert score.type_pair_count == 0


def test_date_accuracy_exact_datetime_match():
    gt = _gt_todo_item("send proposal", due_date=datetime(2026, 6, 4, 17, 0))
    ag = _agent_todo_item("send proposal", due_date=datetime(2026, 6, 4, 17, 0))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 1
    assert score.date_pair_count == 1


def test_date_accuracy_within_60s_tolerance_passes():
    gt = _gt_todo_item("send proposal", due_date=datetime(2026, 6, 4, 17, 0, 0))
    ag = _agent_todo_item("send proposal", due_date=datetime(2026, 6, 4, 17, 0, 45))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 1


def test_date_accuracy_beyond_60s_tolerance_fails():
    gt = _gt_todo_item("send proposal", due_date=datetime(2026, 6, 4, 17, 0, 0))
    ag = _agent_todo_item("send proposal", due_date=datetime(2026, 6, 4, 17, 5, 0))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 0
    assert score.date_pair_count == 1


def test_date_accuracy_gt_window_contains_agent_datetime():
    gt = _gt_todo_item(
        "call dentist",
        due_date_window=TimeWindow(
            start=datetime(2026, 5, 11, 0, 0), end=datetime(2026, 5, 17, 23, 59, 59)
        ),
    )
    ag = _agent_todo_item("call dentist", due_date=datetime(2026, 5, 14, 10, 0))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 1


def test_date_accuracy_gt_window_excludes_agent_datetime():
    gt = _gt_todo_item(
        "call dentist",
        due_date_window=TimeWindow(
            start=datetime(2026, 5, 11, 0, 0), end=datetime(2026, 5, 17, 23, 59, 59)
        ),
    )
    ag = _agent_todo_item("call dentist", due_date=datetime(2026, 5, 20, 10, 0))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 0


def test_date_accuracy_gt_date_only_same_day_passes():
    """Reminder with date-only GT: agent datetime on same day passes."""
    gt = _gt_reminder_item("pick up dry cleaning", remind_at=date(2026, 5, 7))
    ag = _agent_reminder_item(
        "pick up dry cleaning", remind_at=datetime(2026, 5, 7, 15, 30)
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 1


def test_date_accuracy_gt_date_only_different_day_fails():
    gt = _gt_reminder_item("pick up dry cleaning", remind_at=date(2026, 5, 7))
    ag = _agent_reminder_item(
        "pick up dry cleaning", remind_at=datetime(2026, 5, 8, 15, 30)
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 0


def test_date_accuracy_both_null_passes():
    """Reminder with no date on either side -> null==null counts as correct."""
    gt = _gt_reminder_item("vague thought", remind_at=None)
    ag = _agent_reminder_item("vague thought", remind_at=None)
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 1
    assert score.date_pair_count == 1


def test_date_accuracy_gt_null_agent_set_fails():
    gt = _gt_todo_item("buy milk", due_date=None)
    ag = _agent_todo_item("buy milk", due_date=datetime(2026, 5, 7, 17, 0))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 0


def test_date_accuracy_agent_null_gt_set_fails():
    gt = _gt_todo_item("buy milk", due_date=datetime(2026, 5, 7, 17, 0))
    ag = _agent_todo_item("buy milk", due_date=None)
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.date_correct == 0


def test_date_accuracy_only_on_type_matched_pairs():
    """Tier 3 only scores pairs whose Tier 2 type also matched.
    Mismatched-type pair must NOT contribute to date_pair_count."""
    gt = _gt_reminder_item("mom's birthday", remind_at=date(2026, 6, 10))
    ag = _agent_todo_item("mom's birthday", due_date=datetime(2026, 6, 10, 9, 0))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.type_correct == 0
    assert score.date_pair_count == 0
    assert score.date_correct == 0


def test_attribution_todo_assignee_exact_match():
    gt = _gt_todo_item("send proposal", assignee="David")
    ag = _agent_todo_item("send proposal", assignee="David")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 1
    assert score.attribution_pair_count == 1


def test_attribution_todo_assignee_case_insensitive():
    gt = _gt_todo_item("send proposal", assignee="David")
    ag = _agent_todo_item("send proposal", assignee="DAVID")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 1


def test_attribution_todo_assignee_whitespace_stripped():
    gt = _gt_todo_item("send proposal", assignee="David")
    ag = _agent_todo_item("send proposal", assignee="  David  ")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 1


def test_attribution_todo_assignee_mismatch():
    gt = _gt_todo_item("send proposal", assignee="David")
    ag = _agent_todo_item("send proposal", assignee="Sarah")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 0
    assert score.attribution_pair_count == 1


def test_attribution_todo_none_equals_empty_string():
    gt = _gt_todo_item("buy milk", assignee=None)
    ag = _agent_todo_item("buy milk", assignee="")
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 1


def test_attribution_event_attendees_set_equality():
    gt = _gt_event_item(
        "Sprint planning",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        attendees=["Alex", "Jordan"],
    )
    ag = _agent_event_item(
        "Sprint planning",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        attendees=["Jordan", "Alex"],  # different order
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 1


def test_attribution_event_attendees_case_insensitive_strip():
    gt = _gt_event_item(
        "Sprint planning",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        attendees=["Alex", "Jordan"],
    )
    ag = _agent_event_item(
        "Sprint planning",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        attendees=[" alex ", "JORDAN"],
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 1


def test_attribution_event_attendees_mismatch():
    gt = _gt_event_item(
        "Sprint planning",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        attendees=["Alex", "Jordan"],
    )
    ag = _agent_event_item(
        "Sprint planning",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        attendees=["Alex"],
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 0


def test_attribution_event_empty_attendees_both_sides_passes():
    gt = _gt_event_item(
        "Standup",
        start_datetime=datetime(2026, 6, 1, 9, 0),
        attendees=[],
    )
    ag = _agent_event_item(
        "Standup",
        start_datetime=datetime(2026, 6, 1, 9, 0),
        attendees=[],
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_correct == 1


def test_attribution_excludes_reminder_pairs():
    """Reminders have no assignee/attendees -> excluded from attribution denom."""
    gt = _gt_reminder_item("mom's birthday", remind_at=date(2026, 6, 10))
    ag = _agent_reminder_item("mom's birthday", remind_at=date(2026, 6, 10))
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_pair_count == 0
    assert score.attribution_correct == 0


def test_attribution_only_on_type_matched_pairs():
    """Type-mismatched pair (e.g. reminder vs todo) excluded from attribution."""
    gt = _gt_reminder_item("mom's birthday", remind_at=date(2026, 6, 10))
    ag = _agent_todo_item(
        "mom's birthday", due_date=datetime(2026, 6, 10, 9, 0), assignee="Mom"
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.attribution_pair_count == 0


def test_negation_both_false_correct():
    gt = _gt_todo_item("buy milk", negated=False)
    ag = _agent_todo_item("buy milk", negated=False)
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.negation_correct == 1
    assert score.negation_pair_count == 1
    assert score.negation_false_positive == 0
    assert score.negation_false_negative == 0


def test_negation_both_true_correct():
    gt = _gt_todo_item("call dentist", negated=True)
    ag = _agent_todo_item("call dentist", negated=True)
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.negation_correct == 1
    assert score.negation_false_positive == 0
    assert score.negation_false_negative == 0


def test_negation_false_positive_agent_flagged_not_gt():
    """Agent says negated, GT says not. False positive."""
    gt = _gt_todo_item("buy milk", negated=False)
    ag = _agent_todo_item("buy milk", negated=True)
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.negation_correct == 0
    assert score.negation_false_positive == 1
    assert score.negation_false_negative == 0


def test_negation_false_negative_gt_negated_agent_missed():
    """GT says negated, agent missed it. False negative."""
    gt = _gt_todo_item("buy milk", negated=True)
    ag = _agent_todo_item("buy milk", negated=False)
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.negation_correct == 0
    assert score.negation_false_positive == 0
    assert score.negation_false_negative == 1


def test_full_case_composition():
    """
    Realistic mixed case: 3 GT items, 3 agent items.

      gt1 (todo)     -> matched to ag1 (todo), all fields correct
      gt2 (event)    -> matched to ag2 (todo), TYPE MISMATCH
      gt3 (reminder) -> NOT matched (missed)
      ag3 (todo)     -> NOT matched (hallucinated)

    Expected:
      detection:     2 / 3   (2 matched out of 3 GT items)
      hallucination: 1 / 3   (1 phantom out of 3 agent items)
      type:          1 / 2   (gt1 matched; gt2 type mismatched)
      date:          1 / 1   (only gt1's pair contributes; gt2 type-mismatched)
      attribution:   1 / 1   (only gt1's pair contributes)
      negation:      2 / 2   (both matched pairs; both correctly non-negated)
    """
    gt1 = _gt_todo_item(
        "send proposal", due_date=datetime(2026, 6, 4, 17, 0), assignee="David"
    )
    gt2 = _gt_event_item("Sprint planning", start_datetime=datetime(2026, 6, 1, 10, 0))
    gt3 = _gt_reminder_item("mom's birthday", remind_at=date(2026, 6, 10))

    ag1 = _agent_todo_item(
        "send proposal", due_date=datetime(2026, 6, 4, 17, 0), assignee="David"
    )
    ag2 = _agent_todo_item("Sprint planning")  # matched but wrong type
    ag3 = _agent_todo_item("phantom task")  # hallucinated

    match_result = MatchResult(
        matched=[(gt1, ag1), (gt2, ag2)],
        unmatched_gt=[gt3],
        unmatched_agent=[ag3],
    )

    score = score_case(match_result)

    assert score.detection_matched == 2
    assert score.detection_relevant == 3
    assert score.hallucination_unmatched == 1
    assert score.hallucination_relevant == 3
    assert score.type_correct == 1
    assert score.type_pair_count == 2
    assert score.date_correct == 1
    assert score.date_pair_count == 1
    assert score.attribution_correct == 1
    assert score.attribution_pair_count == 1
    assert score.negation_correct == 2
    assert score.negation_pair_count == 2
    assert score.negation_false_positive == 0
    assert score.negation_false_negative == 0


def test_negation_scored_on_type_mismatched_pairs_too():
    """Negation is type-agnostic. A reminder/todo type-mismatched pair STILL
    contributes to negation_pair_count (unlike Tier 3 metrics)."""
    gt = _gt_reminder_item("mom's birthday", remind_at=date(2026, 6, 10), negated=True)
    ag = _agent_todo_item(
        "mom's birthday", due_date=datetime(2026, 6, 10, 9, 0), negated=True
    )
    match_result = MatchResult(matched=[(gt, ag)], unmatched_gt=[], unmatched_agent=[])

    score = score_case(match_result)

    assert score.type_correct == 0
    assert score.negation_pair_count == 1
    assert score.negation_correct == 1
