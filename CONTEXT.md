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
An internal action the user needs to complete. User controls when it happens. Has an optional datetime deadline (`due_date`). The field always stores a full datetime; if the user only mentions a date ("by Friday"), the time defaults to 11:59pm (end of day) of that date.
_Avoid_: task, action item, reminder

**Reminder**:
Something the user needs to be notified about at a specific time or date. Requires no action beyond awareness. Can be all-day (date only) or time-specific (datetime). The "remind me" phrasing in the transcript does NOT promote an action into a Reminder -- classification is based on the underlying intent. "Remind me to call mom tomorrow" is a Todo (calling is an action); "Remind me about Sarah's birthday next week" is a Reminder (awareness only).
_Avoid_: alert, notification, todo

**CalendarEvent**:
An external commitment with a fixed start time the user does not control unilaterally. Has attendees, a location, or both. Blocks calendar time.
_Avoid_: meeting, appointment, event (too generic)

## Relationships

- A **Memo** is transcribed into exactly one **Transcript**
- A **Transcript** is processed by the agent into exactly one **ExtractedMemo**
- An **ExtractedMemo** contains zero or more **TodoItems**, **Reminders**, **CalendarEvents**, and **notes** (free-text observations with no actionable intent. Kept as a pressure valve so the LLM has somewhere to put genuinely non-actionable content rather than forcing it into a todo or reminder)
- A **TodoItem** deadline (`due_date`) is always a `datetime`; if the transcript only mentions a date, the time defaults to 11:59pm that day. In ground truth, the labeler may use `due_date_window` for vague references ("sometime next week").
- A **Reminder** has either a date (all-day) or datetime (time-specific) -- both are valid.
- A **CalendarEvent** always has a fixed start datetime in the **agent's** output; in **ground truth** the labeler may use `start_datetime_window` if the speaker's reference was vague ("camping trip in about two weeks"). The agent must still commit to a single datetime, and the eval checks containment (see ADR-003).

## Flagged ambiguities

- "call dentist at 2pm Thursday" -- resolved: CalendarEvent if it's a booked appointment (external, fixed); TodoItem if the user is just planning to call (internal, moveable).
- "remind me to {action verb}" -- resolved: classify by underlying intent. Action verb → Todo. Awareness-only → Reminder. The "remind me" framing is not a type promoter.
- `assignee` on TodoItem -- resolved: assignee is who PERFORMS the action, not who is mentioned. "Tell Kevin the kickoff is moved" → assignee = null (speaker is telling). "David is handling the summary" → assignee = "David".
- duration_minutes on TodoItem was considered and rejected -- duration is a scheduling detail, not a classification criterion; the internal/external distinction is what separates Todos from CalendarEvents.

See [`docs/labeling-guide.md`](docs/labeling-guide.md) for the full set of labeling conventions (vague time/date encoding, before/by, grocery-list pattern, uncertain events, negation handling, etc.).
