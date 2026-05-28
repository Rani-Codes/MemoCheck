# Test set composition

The public, canonical record of what each test case in `data/transcripts/` is designed to exercise. The eval reads `data/transcripts/*.json` directly; this file provides the human-facing categorization that the eval JSON deliberately omits to stay minimal.

Used by:
- **Reviewers / future reproducers** of the methodology -- to see what each case targets without inspecting the labeled ground truth.
- **The dashboard's per-failure-mode breakdown** -- reads the `Category` column at analysis time to group provider scores by failure mode.
- **The README's *Test set composition* subsection** -- summarizes the counts here at writeup time.

## How the test set is structured

- **22 self-recorded transcripts** -- short voice memos recorded by the project author, transcribed via `scripts/transcribe.py`, then hand-labeled per [`labeling-guide.md`](labeling-guide.md). Audio is not in the public repo (privacy + size); the canonical labeled artifacts are the JSON files in `data/transcripts/`. The verbose per-memo recording scripts live in `reference/voice-memo-scripts.md` (gitignored).
- **8 synthetic edge cases.** Typed transcripts targeting failure modes the self-recorded set under-covers. Locked allocation: 3 Reminder-type cases (the Reminder coverage gap in the self-recorded set) + 5 negation / disfluency / retraction cases (these failure modes need explicit signal beyond memo_021 / memo_022).
- **Visible / held-out split:** 24 visible cases + 6 held-out per [`adr/004-held-out-test-set.md`](adr/004-held-out-test-set.md). The held-out IDs are tracked separately and not inspected during v1 prompt design. The runtime list lives at [`data/held_out_ids.txt`](../data/held_out_ids.txt); the held-out 6 are **memo_001, memo_005, memo_009, memo_011, memo_016, memo_022**.

## Class distribution rationale

The Reminder class (pure awareness, no attached action) is deliberately a small fraction of the test set. Real-world voice memos are overwhelmingly action-driven ("call X", "pick up Y", "send Z") because that is what people actually record memos for. A test set that over-indexed on Reminders would not reflect production usage, so the bulk of the self-recorded set produces Todos and Events. The Reminder class is covered primarily through synthetic edge cases (anniversaries, birthdays, dates of pre-existing appointments). The trade-off accepted: Reminder-specific metrics in the leaderboard will be computed on a smaller N than Todo metrics. This is called out as a limitation in the writeup's methodology section.

## Per-case categorization

The **Split** column indicates whether the case is in the visible-24 set used for v0 / failure-mode analysis / v1 design, or in the held-out-6 set gated until after v1 is designed (per ADR-004).

| ID | Split | Category | Eval target |
|---|---|---|---|
| memo_001 | held-out | type_classification | Todo (not Reminder) when the speaker says "remind me to {verb}"; exact date/time resolution. |
| memo_002 | visible | no_date | Todo extraction without a date; no hallucinated `due_date`. |
| memo_003 | visible | calendar_event_full | CalendarEvent with `location` + `attendees` populated; also adversarially tests negation_false_positive on "Don't want to forget". |
| memo_004 | visible | notes_only | Passive observation -- `notes` populated, all action lists empty. |
| memo_005 | held-out | multi_action | Two Todos in one memo with a shared end-of-day deadline. |
| memo_006 | visible | mixed_types | One booked Event + one deadline-bearing Todo + one dateless Todo in the same memo. |
| memo_007 | visible | calendar_event_attendees | CalendarEvent with multiple named attendees and a location. |
| memo_008 | visible | vague_dates | "Next Thursday at the latest" deadline window + an inner Wednesday review deadline. |
| memo_009 | held-out | vague_dates | "Sometime next week" → open-week window via `due_date_window`. |
| memo_010 | visible | vague_dates | "In about two weeks" → exact memo_recorded_at + 14 days rule. |
| memo_011 | held-out | assignee_semantics | First-person action with a named recipient; `assignee` must be `null` (recipient is not the doer). |
| memo_012 | visible | assignee_semantics | Three first-person actions ("tell X / ask Y / send Z") with named recipients; `assignee` must be `null` for all. |
| memo_013 | visible | multi_action | 5-item memo spanning types, date forms, and deadlines. |
| memo_014 | visible | hallucination_trigger | Numeric financial context ("2.3 million", "12 percent") must not produce fabricated action items. |
| memo_015 | visible | uncertain_event | Hedged reference ("maybe Tuesday?") produces NO CalendarEvent; followup is a Todo + `notes` entry. |
| memo_016 | held-out | multi_action | Sprint deliverables with a shared deadline; also exercises type_classification on "remind me to send". |
| memo_017 | visible | multi_item_pattern | Grocery list collapses to ONE Todo with items in the description; the separate errand is its own Todo. |
| memo_018 | visible | assignee_semantics | First-person action + two named-doer actions ("David is handling", "Lisa's setting up") in one memo. |
| memo_019 | visible | type_classification | "Set a reminder for X to cancel Y" -- action → Todo despite the reminder framing; current-month numeric anchoring. |
| memo_020 | visible | vague_time_of_day | Multi-item memo exercising every vague-time-of-day phrase ("after lunch", "before I leave today", specific times). |
| memo_021 | visible | negation | True retraction ("actually scratch that, I already did it") → item retained with `negated = true`. |
| memo_022 | held-out | negation_false_positive | Mid-thought correction ("3, no wait, 3:30") is NOT negation → single event with `negated = false`. |
| synth_001 | visible | reminder_pure | Pure awareness Reminder (anniversary / birthday / known appointment date) with no attached action; no Todo or Event should be produced. |
| synth_002 | visible | reminder_with_date | Reminder with a vague-date window ("sometime around the holidays") to test Reminder + `remind_at_window` encoding. |
| synth_003 | visible | reminder_with_retraction | Reminder followed by an explicit retraction; tests Negation Handling on the Reminder type (memo_021 covers it only on Todo). |
| synth_004 | visible | negation_explicit | Action item explicitly cancelled mid-memo ("scratch that") on a different item type than memo_021 (e.g. a CalendarEvent or a non-email Todo). |
| synth_005 | visible | negation_partial | Multi-item memo where ONE item is retracted and the others stand; tests that the agent does not over-apply `negated` to neighbors. |
| synth_006 | visible | disfluency_heavy | Restarts, fillers, and run-on phrasing without any negation; pure disfluency stress test. |
| synth_007 | visible | self_correction_value | Mid-sentence value correction on a field other than the time-of-day used in memo_022 (e.g. attendee name, location); must NOT mark `negated`. |
| synth_008 | visible | negation_false_positive | "Don't"-emphasis trap distinct from memo_003's "don't want to forget"; e.g. "remind me NOT to email her back" where `negated = false` because the speaker is reinforcing, not retracting. |

## Category counts (allocation locked; transcripts + GT pending for synth_001..008)

| Category | Count | Cases |
|---|---|---|
| multi_action | 4 | memo_005, memo_013, memo_016, memo_020 |
| vague_dates | 3 | memo_008, memo_009, memo_010 |
| assignee_semantics | 3 | memo_011, memo_012, memo_018 |
| type_classification | 2 | memo_001, memo_019 |
| calendar_event_full | 1 | memo_003 |
| calendar_event_attendees | 1 | memo_007 |
| mixed_types | 1 | memo_006 |
| no_date | 1 | memo_002 |
| notes_only | 1 | memo_004 |
| hallucination_trigger | 1 | memo_014 |
| uncertain_event | 1 | memo_015 |
| multi_item_pattern | 1 | memo_017 |
| vague_time_of_day | 1 | memo_020 |
| negation | 1 | memo_021 |
| negation_false_positive | 1 | memo_022 |
| reminder_pure | 1 | synth_001 |
| reminder_with_date | 1 | synth_002 |
| reminder_with_retraction | 1 | synth_003 |
| negation_explicit | 1 | synth_004 |
| negation_partial | 1 | synth_005 |
| disfluency_heavy | 1 | synth_006 |
| self_correction_value | 1 | synth_007 |
| negation_false_positive | 1 | synth_008 |

Counts re-confirm once GT for synth_001..008 is on disk and re-validated.
