# Labeling Guide

The complete, single-page reference for hand-labeling test cases in `data/transcripts/`. Every convention used by the eval lives here. If you find yourself making a judgment call that isn't covered below, add it (and revisit any existing labels affected by the addition).

The Pydantic models that ground truth must satisfy are in `src/memocheck/evals/schema.py`. Read those alongside this guide.

---

## Quick start: what does a labeled test case look like?

Read this section first. It shows the full shape of a labeled case and three worked examples covering all three item types. The numbered sections below define the rules; this section shows what success looks like.

### Top-level shape

Every test case file (`data/transcripts/memo_NNN.json`) has exactly four top-level fields:

```json
{
  "id": "memo_001",
  "transcript": "<the transcript text the agent will see>",
  "memo_recorded_at": "2026-05-26T10:30:00-04:00",
  "ground_truth": {
    "todos": [],
    "events": [],
    "reminders": [],
    "notes": []
  }
}
```

- `id`: matches the audio filename stem (`memo_001.m4a` → `"memo_001"`).
- `transcript`: the text the agent will see. After running `scripts/transcribe.py`, edit the corresponding `.txt` to lightly fix ASR errors per §1 (errors that change parse / intent / dates), then paste the corrected text into this field. Keep realistic noise (fillers, restarts, run-ons).
- `memo_recorded_at`: TZ-aware ISO 8601 in the recording's *local* timezone (e.g. `-04:00` for EDT). `scripts/transcribe.py` fills this in for you from the audio file's creation timestamp -- you do not normally write it by hand.
- `ground_truth`: contains four lists -- `todos`, `events`, `reminders`, `notes`. Use an empty list `[]` when a list has no items; never `null`.

> The per-case **failure-mode categorization** (e.g. "this case tests negation") lives in [`test-set-composition.md`](test-set-composition.md) as design-doc metadata, not in this JSON. The eval reads only the fields above; the dashboard reads the categorization at analysis time.

### How `scripts/transcribe.py` helps

When you run `python scripts/transcribe.py data/audio/memo_NNN.m4a`, it writes two files into `data/transcripts/`:

1. `memo_NNN.txt` -- the raw transcript. Edit it in place per §1 (ASR corrections).
2. `memo_NNN.json` -- a stub TestCase with `id`, `transcript`, and `memo_recorded_at` already filled in. You fill in `category` and the `ground_truth` contents. The stub is **not** overwritten if it already exists -- it's safe to re-run transcribe on a partially-labeled directory.

### Worked example A: single Todo (memo 01)

Transcript: `"Remind me to call the dentist tomorrow at 2pm. I need to schedule a cleaning."`

The "remind me to {verb}" framing does NOT promote this to a Reminder -- calling is an action. The second sentence is context, not a separate item.

```json
{
  "id": "memo_001",
  "transcript": "Remind me to call the dentist tomorrow at 2pm. I need to schedule a cleaning.",
  "memo_recorded_at": "2026-05-26T10:30:00-04:00",
  "ground_truth": {
    "todos": [
      {
        "description": "call the dentist",
        "due_date": "2026-05-27T14:00:00-04:00",
        "assignee": null,
        "negated": false
      }
    ],
    "events": [],
    "reminders": [],
    "notes": []
  }
}
```

### Worked example B: CalendarEvent with multiple attendees

Transcript: `"Team retrospective is Friday at 2pm in the main conference room. Alex, Jordan, and Sam all need to be there."`

A booked, fixed-time, external commitment → CalendarEvent, not Todo.

```json
{
  "id": "memo_007",
  "transcript": "Team retrospective is Friday at 2pm in the main conference room. Alex, Jordan, and Sam all need to be there.",
  "memo_recorded_at": "2026-05-26T15:00:00-04:00",
  "ground_truth": {
    "todos": [],
    "events": [
      {
        "title": "Team retrospective",
        "start_datetime": "2026-05-29T14:00:00-04:00",
        "duration_minutes": null,
        "location": "main conference room",
        "attendees": ["Alex", "Jordan", "Sam"],
        "negated": false
      }
    ],
    "reminders": [],
    "notes": []
  }
}
```

Note `duration_minutes: null` -- the speaker did not say how long the meeting runs, so we do not infer.

### Worked example C: mixed types in one memo (Todo + Event + Todo with vague-date window)

Transcript: `"Okay three things. Dentist appointment is confirmed for Tuesday at 3pm. Remind me to pay the credit card bill before Friday. And I still need to buy a birthday card for mom."`

Three distinct items, three different types. The "before Friday" deadline uses the **window form** (`due_date_window`) because it's a constraint, not an exact moment. The mom card has no date at all.

```json
{
  "id": "memo_006",
  "transcript": "Okay three things. Dentist appointment is confirmed for Tuesday at 3pm. Remind me to pay the credit card bill before Friday. And I still need to buy a birthday card for mom.",
  "memo_recorded_at": "2026-05-26T12:15:00-04:00",
  "ground_truth": {
    "todos": [
      {
        "description": "pay the credit card bill",
        "due_date": null,
        "due_date_window": {"end": "2026-05-28T23:59:00-04:00"},
        "assignee": null,
        "negated": false
      },
      {
        "description": "buy a birthday card for mom",
        "due_date": null,
        "assignee": null,
        "negated": false
      }
    ],
    "events": [
      {
        "title": "Dentist appointment",
        "start_datetime": "2026-05-26T15:00:00-04:00",
        "duration_minutes": null,
        "location": null,
        "attendees": [],
        "negated": false
      }
    ],
    "reminders": [],
    "notes": []
  }
}
```

Three things to notice in this example:

1. **`due_date` vs `due_date_window` are mutually exclusive.** The first todo uses `due_date_window` (because "before Friday" is a range), so its `due_date` is `null`. The second todo has no date at all, so both are absent / null.
2. **"Before Friday" → `{end: <Thursday> 23:59}` (open start).** Per §7, "before {weekday}" means *prior weekday EOD*. Friday was 2026-05-29 in this example, so the deadline lands on Thursday 2026-05-28.
3. **The credit-card item is a Todo, not a Reminder.** "Pay" is an action; the "remind me to" framing does not promote it to a Reminder. See §2.

### What an empty ground truth looks like

If a memo is purely observational ("just a note: the back door lock is sticking"), the ground truth has only `notes`:

```json
"ground_truth": {
  "todos": [],
  "events": [],
  "reminders": [],
  "notes": ["back door lock is sticking again"]
}
```

Never use `null` for a list field. Always `[]`.

---

## 0. Source-of-truth precedence

When two documents conflict, this guide wins for *labeling decisions*. CLAUDE.md and CONTEXT.md should reference this file rather than restate its rules.

---

## 1. ASR error correction (do this before labeling)

The transcript produced by `scripts/transcribe.py` is the input the agent will see. Lightly fix transcription errors that would confound the eval, but preserve realistic noise.

| Pattern | Action |
|---|---|
| Missing function words that change the parse ("Ask Rachel she can cover" → "Ask Rachel **if** she can cover") | **Fix** in the `.txt` |
| Proper nouns misheard when they're the action's anchor ("Mulgreens" → "Walgreens"; "Sara" → "Sarah") | **Fix** |
| Numbers / times / weekdays misheard ("20" → "2:30", "Tuesday" → "Thursday") | **Fix always** -- these drive Tier 3 (Date Accuracy) |
| Filler words ("uh", "okay so", "let me think") | **Leave as-is** -- realistic noise we want to test against |
| Restarts, run-on sentences, missing punctuation | **Leave as-is** -- same |
| Misheard proper noun that's only incidental (a person mentioned in passing, not the assignee or recipient) | Prefer leave -- fix only if it would confuse the labeler |

### Why this rule

MemoCheck benchmarks the LLM's *intent-extraction* layer, not its ability to repair mangled ASR output. If half the cases have garbled words, the metrics conflate two unrelated failure modes (transcription + extraction) and the v0 → v1 story becomes harder to read. Surface noise (fillers, restarts) is real production noise the agent should handle; word-level transcription errors that destroy parseable meaning are not part of the task we are measuring.

### Workflow

1. Run `scripts/transcribe.py data/audio/` → produces `data/transcripts/memo_NNN.txt`.
2. Read the `.txt` alongside playing back the `.m4a`. Apply the table above; edit the `.txt` in place. Edits should be minimal.
3. Copy the corrected text into the `transcript` field of `data/transcripts/memo_NNN.json` and proceed with the rest of this guide.

The `.txt` file is the editable stepping-stone. The `.json` is the canonical artifact the eval reads.

---

## 2. Type classification (Todo vs Reminder vs CalendarEvent)

Classify by **underlying intent**, not by phrasing.

| Intent | Type | Example |
|---|---|---|
| The speaker (or a named person) needs to DO something | **TodoItem** | "Pick up the dry cleaning Thursday" |
| The speaker needs to be AWARE of something at a time/date, with no action attached | **Reminder** | "Remind me about Sarah's birthday next Friday" |
| A booked, fixed-time, external commitment (someone else also holds it; not unilaterally moveable) | **CalendarEvent** | "Dentist appointment is confirmed for Wednesday at 3pm" |

### Rules of thumb

- **"Remind me to {action verb}"** → **Todo**. The "remind me" framing does not override action content. "Remind me to call mom" is a Todo, not a Reminder. The discriminator is whether the underlying intent is an action.
- **"Remind me about {thing}" / "Remind me of {fact}"** → **Reminder**. Pure awareness.
- **"X is confirmed/booked/scheduled"** → **CalendarEvent**.
- **"I'm planning to X" / "I need to X"** → **TodoItem**, even when X happens to involve another person.

### Edge case: explicit reminder request for an action

"Set a reminder for the 18th to cancel my gym membership." → **Todo** ("cancel" is an action). The "set a reminder" framing is treated like "remind me to" -- it sets the deadline, it doesn't promote the type. Use the user's stated reminder date as the Todo's `due_date` / `due_date_window` end.

### Edge case: uncertain events

If the speaker is uncertain about an event ("there might be an appointment, maybe Tuesday?"), do **not** create a CalendarEvent. Capture:
- the followup action (e.g. "check with the office to confirm") as a Todo, and
- the uncertain reference as a string in `notes` (e.g. `"possibly a doctor's appointment next week, maybe Tuesday"`).

This avoids rewarding the agent for confident hallucination.

---

## 3. Assignee semantics

`TodoItem.assignee` is the person who **performs** the action, not whoever is mentioned in the description.

| Pattern | `assignee` |
|---|---|
| First-person action ("I need to X", "I'll handle Y") | `null` |
| "Tell X / Ask X / Send X about Y" (speaker is the one telling/asking/sending) | `null` -- X is the recipient |
| "X is handling Y / X is setting up Y / X will do Y" (X is the doer) | `"X"` |
| "Have X do Y" / "X needs to Y" | `"X"` |

When in doubt: ask "who actually performs this action?" That person is the assignee. If it's the speaker, `assignee = null`.

`CalendarEvent.attendees` is unrelated to assignee -- it's the list of people who attend the event, including possibly the speaker.

---

## 4. Date encoding

Two forms exist for each date field on every ground-truth model:

| Field on GT model | Form | Use when |
|---|---|---|
| `due_date` / `remind_at` / `start_datetime` | exact `datetime` (or `date` for Reminder) | the speaker specified an exact moment |
| `due_date_window` / `remind_at_window` / `start_datetime_window` | `TimeWindow{start, end}` (both optional) | the speaker was vague (range, before-X, after-X, day-of-week) |

Exactly one of the two fields must be set per item -- or neither (date unknown, leave both null).

### Time defaults for date-only references

- Speaker mentioned a date but no time → the time defaults to **23:59** (end of day) on that date when set as an exact datetime, OR encoded as a day-window (`{start: that day 00:00, end: that day 23:59}`).
- Use a day-window when the speaker's intent is "anytime on that day"; use 23:59 when the speaker's intent is "by end of that day".

### Mixed date types (date vs datetime)

The agent emits a `date` or a `datetime`; ground truth may use either form. The eval normalizes both sides into a window-overlap check (see ADR-003), so:
- A ground-truth `date` is compared as the window `[date 00:00:00, date 23:59:59]`.
- A ground-truth `datetime` is compared as a point with ±60s tolerance.
- A ground-truth `TimeWindow` is used as-is.

You do not need to worry about which form the agent uses; just label the speaker's actual constraint faithfully.

### Anchoring numeric references to the current month

"The 18th" / "the 20th" / "the 3rd" → resolve to that day of the **current month** as of `memo_recorded_at`. Make this explicit when writing the ground truth (e.g. a comment in the JSON or the test-case `id`).

If the resolved date is in the past relative to `memo_recorded_at`, advance to the same day in the next month.

---

## 5. Vague time-of-day → window

Anchored to `memo_recorded_at`'s local day. For relative-day phrases ("tomorrow morning"), apply the day offset first, then the window.

| Phrase | Window |
|---|---|
| "morning" | `{start: 06:00, end: 12:00}` |
| "midday" / "lunch" | `{start: 12:00, end: 13:00}` |
| "afternoon" | `{start: 12:00, end: 18:00}` |
| "after lunch" | `{start: 13:00, end: 17:00}` |
| "evening" | `{start: 18:00, end: 22:00}` |
| "tonight" | `{start: 18:00, end: 23:59}` |
| "end of day" / "EOD" | `{end: 23:59}` (open start) |
| "before I leave today" | `{end: 18:00}` (open start, work-day end) |
| "early {X}" | shift the **start** earlier by ~1h |
| "late {X}" | shift the **end** later by ~1h |

If a phrase isn't on this table, encode as the full day window (`{start: that day 00:00, end: that day 23:59}`) and leave a `# TODO labeler: unhandled vague-time phrase: "..."` comment alongside the case so we can extend the table rather than silently invent rules.

---

## 6. Vague relative-date → window

Anchored to `memo_recorded_at`.

| Phrase | Encoding |
|---|---|
| "in about two weeks" | exact `memo_recorded_at + 14 days` (not a window -- this is a deterministic shortcut by project rule) |
| "in about a month" | exact `memo_recorded_at + 30 days` (same rule) |
| "sometime next week" | `{start: <Mon of next week> 00:00, end: <Sun of next week> 23:59}` |
| "sometime this week" | `{start: <today> 00:00, end: <Sun of this week> 23:59}` |
| "this month" / "by end of month" | `{end: <last day of current month> 23:59}` (open start) |
| "by next {weekday}" | `{end: <that weekday> 23:59}` (open start) |

"Next week" means the calendar week starting next Monday, not "the next seven days."

---

## 7. "Before" vs "by"

| Phrase | Encoding |
|---|---|
| "before {weekday}" | `{end: <previous weekday> 23:59}` (open start) |
| "by {weekday}" | `{end: <that weekday> 23:59}` (open start) |
| "no later than {weekday}" | same as "by {weekday}" |
| "after {weekday}" | `{start: <that weekday + 1 day> 00:00}` (open end) |

Example: "before Friday" → `{end: Thursday 23:59}`. "By Friday" → `{end: Friday 23:59}`.

---

## 8. Multi-item / shopping list pattern

A single breath listing multiple items of the same kind ("eggs, milk, sourdough, the good olive oil") collapses to **one TodoItem** with the items in the description, not N separate todos. Example:

```json
{"description": "grocery run (eggs, milk, sourdough, olive oil from the Italian section)",
 "due_date": null, "assignee": null, "negated": false}
```

A separate errand in the same memo is its own Todo. Use the "same trip / same action" intuition: if the speaker would treat it as one trip to one place, one Todo. If it's a distinct outing, separate Todo.

---

## 9. Negation handling

The `negated` flag captures explicit retractions of items the speaker mentioned.

### Set `negated = true` when

- The speaker explicitly cancels a mentioned item: "scratch that", "never mind", "actually no", "don't bother", "I already did it".
- The original mention must remain in the output -- do **not** delete the item. The metric measures whether the agent detects the retraction; if you delete the item, both the agent and the labeler lose the signal.

### Set `negated = false` (or leave default) when

- The speaker corrects a value mid-sentence ("3, no wait, 3:30 on Thursday"). Produce only the corrected value. No `negated = true`.
- The speaker emphasizes a positive ("don't want to forget", "don't be late"). The word "don't" appears but the intent is not retraction.
- The speaker hedges with uncertainty ("maybe", "I think"). Uncertainty is not negation. (See §2 edge case on uncertain events.)

### Two error directions tracked by the metric

- **False-positive negation:** agent marks `negated = true` when the speaker did not retract. Tested by memos like 03 ("don't want to forget") and 22 (mid-thought correction).
- **False-negative negation:** agent misses a real retraction (item appears with `negated = false`, or is omitted entirely). Tested by memo 21 and most of the synthetic retraction cases.

Both directions are reported separately in the leaderboard.

---

## 10. Notes (the `notes: list[str]` field)

`notes` is a pressure valve for content that is genuinely non-actionable and does not fit a Todo / Reminder / CalendarEvent. The `notes` field is **not graded** by any metric (see CLAUDE.md > Metrics > "Not scored"), but it is inspected qualitatively. Label it honestly anyway -- the agent's note-routing behavior is examined during failure-mode analysis.

Use `notes` for:
- Observational context ("Q3 came in at ~2.3M, ~12% above Q2")
- Uncertain references that don't justify a typed entry ("possibly a doctor's appointment next week, maybe Tuesday")
- Background / framing the speaker added that isn't an action

Do **not** route real actions into `notes` to dodge type classification -- if it's an action, it goes in `todos`.

---

## 11. Timezone and `memo_recorded_at`

**All datetimes in a single test case share the same timezone: the recording's local timezone with an explicit ISO 8601 offset** (e.g. `-04:00` for EDT, `-05:00` for EST). This applies to `memo_recorded_at`, every `due_date`, every `start_datetime`, every `remind_at`, and every `TimeWindow.start` / `TimeWindow.end`. They must all carry the same offset string.

### Why local-with-offset, not UTC

The labeler reads "tomorrow at 2pm" in the transcript and interprets it in their head as 2pm *local* time. If ground truth were UTC, the labeler would do a mental TZ conversion on every datetime. By using local-with-offset, the labeler types the time they hear and appends a fixed offset string. The eval compares instants -- mathematically equivalent to UTC -- but ergonomically far better for labeling.

### How `memo_recorded_at` is set

You don't normally write it by hand. `scripts/transcribe.py` reads the audio file's creation timestamp (`st_birthtime` on macOS), converts to the system's local timezone, and serializes as ISO 8601 with offset. Example output: `"2026-05-26T10:30:00-04:00"`.

If you need to set it manually, the macOS one-liner is:

```bash
python3 -c "from pathlib import Path; from datetime import datetime; \
p = Path('data/audio/memo_001.m4a'); ts = p.stat().st_birthtime; \
print(datetime.fromtimestamp(ts).astimezone().isoformat(timespec='seconds'))"
```

### Constraints for the v0 test set

- Every recording is assumed to be in the speaker's local timezone.
- DST is not handled specially; if a recording straddles a DST transition (e.g. recorded on a Sunday morning when clocks shifted), the offset chosen is whichever the speaker is operating in at recording time.
- Cross-timezone scenarios (recorded in one TZ, referencing events in another) are out of scope for v0. v2 may revisit.

---

## 12. CalendarEvent specifics

- `start_datetime` (agent) is always a single datetime. `start_datetime_window` (ground truth only) is allowed for vague references; the agent's committed datetime must fall inside the window.
- `duration_minutes` is optional; only set it if the speaker explicitly mentioned a duration ("the meeting is 30 minutes long"). Do not infer from context.
- `location` is optional; set it only if the speaker named a place. Do not infer ("the meeting" → don't guess "conference room").
- `attendees` is the list of people who attend. Do not include the speaker unless the speaker named themselves explicitly. Strip titles ("Dr. Khan" → "Dr. Khan" if that's what was said, otherwise just "Khan").

---

## 13. Sanity checklist before saving a case

1. The JSON validates against `TestCase` in `src/memocheck/evals/schema.py`.
2. `memo_recorded_at` is a TZ-aware ISO 8601 datetime with an explicit offset (e.g. `-04:00`); every other datetime in the case carries the same offset string (see §11).
3. Every date field on every item is either an exact form or a window form -- never both (Pydantic enforces this, but check anyway).
4. Every `TodoItem` has a verb in the description (it's an *action*).
5. Every `assignee` is the *doer*, not the *recipient*.
6. Every `negated = true` item is one the speaker actually retracted in the transcript.
7. No real actions are hiding in `notes`.
8. Numeric references like "the 18th" resolved to the correct month per `memo_recorded_at`.
9. Any vague-time phrase not on the §5 table has a `# TODO labeler:` comment so we extend the table later.

---

## 14. When the rule book is wrong

If you label a case and it feels wrong against this guide, the guide is probably the thing to fix. Open the case + this file side by side, propose the rule change in plain English, then update both. Don't quietly label against an unwritten rule -- that's how the test set ends up inconsistent.
