# MemoCheck

An eval-driven pipeline that turns voice memo audio into structured JSON intent via LLM extraction.

## Language

**Memo**:
A raw audio file recorded by the user. The starting artifact -- never processed directly by the agent.
_Avoid_: audio file, recording, voice note

**Transcript**:
The text produced by transcribing a Memo. This is what the agent receives as input.
_Avoid_: memo text, raw text, audio transcript

**ExtractedMemo**:
The structured JSON output produced by the agent from a Transcript. Contains todos, events, reminders, and notes.
_Avoid_: structured output, parsed memo, intent, result

**TodoItem**:
An internal action the user needs to complete. User controls when it happens. Has an optional date-level deadline -- not a specific time.
_Avoid_: task, action item, reminder

**Reminder**:
Something the user needs to be notified about at a specific time or date. Requires no action beyond awareness. Can be all-day (date only) or time-specific (datetime).
_Avoid_: alert, notification, todo

**CalendarEvent**:
An external commitment with a fixed start time the user does not control unilaterally. Has attendees, a location, or both. Blocks calendar time.
_Avoid_: meeting, appointment, event (too generic)

## Relationships

- A **Memo** is transcribed into exactly one **Transcript**
- A **Transcript** is processed by the agent into exactly one **ExtractedMemo**
- An **ExtractedMemo** contains zero or more **TodoItems**, **Reminders**, **CalendarEvents**, and **notes** (free-text observations with no actionable intent. Kept as a pressure valve so the LLM has somewhere to put genuinely non-actionable content rather than forcing it into a todo or reminder)
- A **TodoItem** deadline is a datetime; if only a date is mentioned, default to 11:59pm that day
- A **Reminder** has either a date (all-day) or datetime (time-specific) -- both are valid
- A **CalendarEvent** always has a fixed start datetime; a TodoItem never does

## Flagged ambiguities

- "call dentist at 2pm Thursday" -- resolved: CalendarEvent if it's a booked appointment (external, fixed); TodoItem if the user is just planning to call (internal, moveable)
- duration_minutes on TodoItem was considered and rejected -- duration is a scheduling detail, not a classification criterion; the internal/external distinction is what separates Todos from CalendarEvents
