# Test set composition

The public, canonical record of what each test case in `data/transcripts/` is designed to exercise. The eval reads `data/transcripts/*.json` directly; this file provides the human-facing categorization that the eval JSON deliberately omits to stay minimal.

Used by:
- **Reviewers / future reproducers** of the methodology -- to see what each case targets without inspecting the labeled ground truth.
- **The dashboard's per-failure-mode breakdown** -- reads the `Category` column at analysis time to group provider scores by failure mode.
- **The README's *Test set composition* subsection** -- summarizes the counts here at writeup time.

## How the test set is structured

- **22 self-recorded transcripts** -- short voice memos recorded by the project author, transcribed via `scripts/transcribe.py`, then hand-labeled per [`labeling-guide.md`](labeling-guide.md). Audio is not in the public repo (privacy + size); the canonical labeled artifacts are the JSON files in `data/transcripts/`. The verbose per-memo recording scripts live in `reference/voice-memo-scripts.md` (gitignored).
- **8 synthetic edge cases** (TBD -- not yet authored). Typed transcripts targeting failure modes the self-recorded set under-covers (negation, disfluency, and retraction primarily).
- **Visible / held-out split:** 24 visible cases + 6 held-out per [`adr/004-held-out-test-set.md`](adr/004-held-out-test-set.md). The held-out IDs are tracked separately and not inspected during v1 prompt design.

## Per-case categorization

| ID | Category | Eval target |
|---|---|---|
| memo_001 | type_classification | Todo (not Reminder) when the speaker says "remind me to {verb}"; exact date/time resolution. |
| memo_002 | no_date | Todo extraction without a date; no hallucinated `due_date`. |
| memo_003 | calendar_event_full | CalendarEvent with `location` + `attendees` populated; also adversarially tests negation_false_positive on "Don't want to forget". |
| memo_004 | notes_only | Passive observation -- `notes` populated, all action lists empty. |
| memo_005 | multi_action | Two Todos in one memo with a shared end-of-day deadline. |
| memo_006 | mixed_types | One booked Event + one deadline-bearing Todo + one dateless Todo in the same memo. |
| memo_007 | calendar_event_attendees | CalendarEvent with multiple named attendees and a location. |
| memo_008 | vague_dates | "Next Thursday at the latest" deadline window + an inner Wednesday review deadline. |
| memo_009 | vague_dates | "Sometime next week" → open-week window via `due_date_window`. |
| memo_010 | vague_dates | "In about two weeks" → exact memo_recorded_at + 14 days rule. |
| memo_011 | assignee_semantics | First-person action with a named recipient; `assignee` must be `null` (recipient is not the doer). |
| memo_012 | assignee_semantics | Three first-person actions ("tell X / ask Y / send Z") with named recipients; `assignee` must be `null` for all. |
| memo_013 | multi_action | 5-item memo spanning types, date forms, and deadlines. |
| memo_014 | hallucination_trigger | Numeric financial context ("2.3 million", "12 percent") must not produce fabricated action items. |
| memo_015 | uncertain_event | Hedged reference ("maybe Tuesday?") produces NO CalendarEvent; followup is a Todo + `notes` entry. |
| memo_016 | multi_action | Sprint deliverables with a shared deadline; also exercises type_classification on "remind me to send". |
| memo_017 | multi_item_pattern | Grocery list collapses to ONE Todo with items in the description; the separate errand is its own Todo. |
| memo_018 | assignee_semantics | First-person action + two named-doer actions ("David is handling", "Lisa's setting up") in one memo. |
| memo_019 | type_classification | "Set a reminder for X to cancel Y" -- action → Todo despite the reminder framing; current-month numeric anchoring. |
| memo_020 | vague_time_of_day | Multi-item memo exercising every vague-time-of-day phrase ("after lunch", "before I leave today", specific times). |
| memo_021 | negation | True retraction ("actually scratch that, I already did it") → item retained with `negated = true`. |
| memo_022 | negation_false_positive | Mid-thought correction ("3, no wait, 3:30") is NOT negation → single event with `negated = false`. |
| synth_001 | TBD | TBD -- to be authored. Likely target: synthetic retraction with disfluency. |
| synth_002 | TBD | TBD. |
| synth_003 | TBD | TBD. |
| synth_004 | TBD | TBD. |
| synth_005 | TBD | TBD. |
| synth_006 | TBD | TBD. |
| synth_007 | TBD | TBD. |
| synth_008 | TBD | TBD. |

## Category counts (preliminary -- 22 of 30 cases categorized)

| Category | Count | Memos |
|---|---|---|
| multi_action | 4 | 5, 13, 16, 20 |
| vague_dates | 3 | 8, 9, 10 |
| assignee_semantics | 3 | 11, 12, 18 |
| type_classification | 2 | 1, 19 |
| calendar_event_full | 1 | 3 |
| calendar_event_attendees | 1 | 7 |
| mixed_types | 1 | 6 |
| no_date | 1 | 2 |
| notes_only | 1 | 4 |
| hallucination_trigger | 1 | 14 |
| uncertain_event | 1 | 15 |
| multi_item_pattern | 1 | 17 |
| vague_time_of_day | 1 | 20 |
| negation | 1 | 21 |
| negation_false_positive | 1 | 22 |
| TBD (synthetic) | 8 | synth_001..008 |

Once the synthetic cases are authored, lock the final counts before running v1.
