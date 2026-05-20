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
    raw_response: str
