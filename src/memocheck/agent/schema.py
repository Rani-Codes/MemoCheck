from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel


class TodoItem(BaseModel):
    description: str
    due_date: Optional[date] = None
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
    remind_at: Optional[datetime] = None
    negated: bool = False


class Entity(BaseModel):
    name: str
    kind: Literal["person", "place", "organization"]


class ExtractedMemo(BaseModel):
    todos: list[TodoItem] = []
    events: list[CalendarEvent] = []
    reminders: list[Reminder] = []
    notes: list[str] = []
    entities: list[Entity] = []


class ExtractionError(BaseModel):
    error: str
    raw_response: str
