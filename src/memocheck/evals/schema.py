"""
Ground truth schema for the evaluation suite.

Human labelers use these models to write the expected output for each test
case. The eval scorer compares an agent's output (from
`memocheck.agent.schema`) against these instances.

TL;DR: the agent must commit to exactly one datetime, but the ground truth
can accept a range of valid answers (e.g. "sometime next week" becomes a
TimeWindow covering that week). That asymmetry is why this file exists
separately from the agent schema. See ADR-003 for the rationale.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, model_validator


class TimeWindow(BaseModel):
    """An inclusive time window. Either bound may be omitted to leave that side open."""

    start: Optional[datetime] = None
    end: Optional[datetime] = None

    @model_validator(mode="after")
    def at_least_one_bound(self) -> "TimeWindow":
        if self.start is None and self.end is None:
            raise ValueError("TimeWindow must specify at least one of start or end")
        return self

    def contains(self, dt: datetime) -> bool:
        if self.start is not None and dt < self.start:
            return False
        if self.end is not None and dt > self.end:
            return False
        return True


class GroundTruthTodoItem(BaseModel):
    description: str
    due_date: Optional[datetime] = None
    due_date_window: Optional[TimeWindow] = None
    assignee: Optional[str] = None
    negated: bool = False

    @model_validator(mode="after")
    def date_fields_mutually_exclusive(self) -> "GroundTruthTodoItem":
        if self.due_date is not None and self.due_date_window is not None:
            raise ValueError(
                "GroundTruthTodoItem must set at most one of due_date / due_date_window"
            )
        return self


class GroundTruthCalendarEvent(BaseModel):
    title: str
    start_datetime: Optional[datetime] = None
    start_datetime_window: Optional[TimeWindow] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    attendees: list[str] = []
    negated: bool = False

    @model_validator(mode="after")
    def start_must_be_specified(self) -> "GroundTruthCalendarEvent":
        if self.start_datetime is None and self.start_datetime_window is None:
            raise ValueError(
                "GroundTruthCalendarEvent must specify "
                "start_datetime or start_datetime_window"
            )
        if self.start_datetime is not None and self.start_datetime_window is not None:
            raise ValueError(
                "GroundTruthCalendarEvent must set at most one of "
                "start_datetime / start_datetime_window"
            )
        return self


class GroundTruthReminder(BaseModel):
    description: str
    remind_at: Optional[date | datetime] = None
    remind_at_window: Optional[TimeWindow] = None
    negated: bool = False

    @model_validator(mode="after")
    def date_fields_mutually_exclusive(self) -> "GroundTruthReminder":
        if self.remind_at is not None and self.remind_at_window is not None:
            raise ValueError(
                "GroundTruthReminder must set at most one of "
                "remind_at / remind_at_window"
            )
        return self


class GroundTruthExtractedMemo(BaseModel):
    todos: list[GroundTruthTodoItem] = []
    events: list[GroundTruthCalendarEvent] = []
    reminders: list[GroundTruthReminder] = []
    notes: list[str] = []


class TestCase(BaseModel):
    id: str
    transcript: str
    memo_recorded_at: datetime
    ground_truth: GroundTruthExtractedMemo
