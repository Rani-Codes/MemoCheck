from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class TodoItem(BaseModel):
    description: str
    due_date: Optional[datetime] = None  # date-only input defaults to 11:59pm that day
    assignee: Optional[str] = None
    negated: bool = False


class CalendarEvent(BaseModel):
    title: str
    start_datetime: datetime
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    attendees: list[str] = []
    negated: bool = False


class Reminder(BaseModel):
    description: str
    remind_at: Optional[date | datetime] = None
    negated: bool = False


class ExtractedMemo(BaseModel):
    todos: list[TodoItem] = []
    events: list[CalendarEvent] = []
    reminders: list[Reminder] = []
    notes: list[str] = []


class ExtractionError(BaseModel):
    error: str


class ExtractionResult(BaseModel):
    """Full return type of `extract()`. Carries both the parsed output and the
    raw LLM text, so eval / debugging can inspect what the model literally said
    before parsing."""

    output: ExtractedMemo | ExtractionError
    # True iff the FIRST LLM attempt produced JSON that passed strict Pydantic
    # validation. Validation that only passes after the once-allowed retry must
    # set this to False -- the Schema Adherence metric (see CLAUDE.md) measures
    # first-attempt validity, not best-of-N.
    schema_valid: bool
    latency_ms: int
    cost_usd: float
    raw_response: str
