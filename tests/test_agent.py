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


from unittest.mock import MagicMock, patch

from memocheck.agent.extractor import extract
from memocheck.agent.prompts.v0 import SYSTEM_PROMPT as V0_PROMPT


def _mock_litellm_response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def test_extract_returns_extracted_memo_on_valid_response():
    valid_json = ExtractedMemo(
        reminders=[Reminder(description="call dentist")]
    ).model_dump_json()

    with patch("memocheck.agent.extractor.litellm.completion") as mock_completion, \
         patch("memocheck.agent.extractor.litellm.completion_cost", return_value=0.001):
        mock_completion.return_value = _mock_litellm_response(valid_json)

        result, schema_valid, latency_ms, cost_usd = extract(
            transcript="Remind me to call the dentist.",
            memo_recorded_at="2026-05-08T09:00:00Z",
            model="openai/gpt-4.1-mini",
            system_prompt=V0_PROMPT,
        )

    assert isinstance(result, ExtractedMemo)
    assert schema_valid is True
    assert latency_ms >= 0
    assert cost_usd == 0.001


def test_extract_retries_on_validation_error_and_succeeds():
    bad_json = '{"todos": "not a list"}'
    valid_json = ExtractedMemo().model_dump_json()

    with patch("memocheck.agent.extractor.litellm.completion") as mock_completion, \
         patch("memocheck.agent.extractor.litellm.completion_cost", return_value=0.001):
        mock_completion.side_effect = [
            _mock_litellm_response(bad_json),
            _mock_litellm_response(valid_json),
        ]

        result, schema_valid, latency_ms, cost_usd = extract(
            transcript="Nothing actionable here.",
            memo_recorded_at="2026-05-08T09:00:00Z",
            model="openai/gpt-4.1-mini",
            system_prompt=V0_PROMPT,
        )

    assert isinstance(result, ExtractedMemo)
    assert schema_valid is False
    assert mock_completion.call_count == 2


def test_extract_returns_extraction_error_after_two_failures():
    bad_json = '{"todos": "not a list"}'

    with patch("memocheck.agent.extractor.litellm.completion") as mock_completion, \
         patch("memocheck.agent.extractor.litellm.completion_cost", return_value=0.001):
        mock_completion.return_value = _mock_litellm_response(bad_json)

        result, schema_valid, latency_ms, cost_usd = extract(
            transcript="Nothing actionable here.",
            memo_recorded_at="2026-05-08T09:00:00Z",
            model="openai/gpt-4.1-mini",
            system_prompt=V0_PROMPT,
        )

    assert isinstance(result, ExtractionError)
    assert schema_valid is False
    assert mock_completion.call_count == 2
