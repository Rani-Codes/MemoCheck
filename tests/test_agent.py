import json
from datetime import date, datetime

import pytest

from memocheck.agent.schema import (
    CalendarEvent,
    Entity,
    ExtractedMemo,
    ExtractionError,
    Reminder,
    TodoItem,
)


def test_extracted_memo_defaults_to_empty_lists():
    memo = ExtractedMemo()
    assert memo.todos == []
    assert memo.events == []
    assert memo.reminders == []
    assert memo.notes == []
    assert memo.entities == []


def test_todo_item_optional_fields_default_to_none():
    todo = TodoItem(description="Buy milk")
    assert todo.due_date is None
    assert todo.assignee is None


def test_calendar_event_attendees_defaults_to_empty():
    event = CalendarEvent(
        title="Team standup",
        start_datetime=datetime(2026, 5, 11, 9, 0),
    )
    assert event.attendees == []
    assert event.duration_minutes is None
    assert event.location is None


def test_entity_kind_is_validated():
    entity = Entity(name="Alice", kind="person")
    assert entity.kind == "person"

    with pytest.raises(Exception):
        Entity(name="Nowhere", kind="invalid_kind")


def test_extracted_memo_round_trips_json():
    memo = ExtractedMemo(
        todos=[TodoItem(description="Call dentist", due_date=date(2026, 5, 15))],
        reminders=[Reminder(description="Pick up dry cleaning")],
        notes=["General note here"],
        entities=[Entity(name="Dr. Smith", kind="person")],
    )
    json_str = memo.model_dump_json()
    restored = ExtractedMemo.model_validate_json(json_str)
    assert restored.todos[0].description == "Call dentist"
    assert restored.entities[0].kind == "person"


def test_extraction_error_stores_raw_response():
    err = ExtractionError(error="ValidationError", raw_response='{"bad": "json"}')
    assert err.error == "ValidationError"
    assert err.raw_response == '{"bad": "json"}'
