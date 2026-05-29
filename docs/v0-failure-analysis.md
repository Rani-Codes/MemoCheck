# v0 failure-mode analysis (visible-24)

Read-only analysis of the v0 run to identify the top failure modes that drive v1 prompt
design. **No held-out data was opened or run.** Visible-24 slice only, per ADR-004.

**Scoring note:** these numbers use the **judged-band matcher** (auto-accept cosine
>= 0.80, auto-reject < 0.50, Claude Sonnet 4.6 judges in between), adopted after the
mandatory matcher spot-check. The earlier single-0.80-cutoff figures (detection 92.1%,
hallucination 12.0%) were inflated/deflated by sub-threshold false negatives and are
superseded here; see `docs/v0-matcher-validation.md` for the change and its rationale.

## Method

- **Source:** `test_runs` + `metric_scores` in Postgres, `agent_version='v0'`,
  `error_message IS NULL`. 4 providers x 24 visible cases x 3 attempts = 288 runs.
- **Aggregation:** micro-average, `SUM(numerator) / SUM(denominator)`. Never `AVG(score)`.
- **Category map:** built from `docs/test-set-composition.md` (per-case Category column;
  `memo_020 = vague_time_of_day`), joined in code. Visible-24 only.
- **Error-direction metrics:** `hallucination_rate`, `negation_false_positive`,
  `negation_false_negative` are *error* rates where lower is better. All others are
  accuracy where higher is better.

## Headline

1. **Date accuracy: 80.5% (376/467) is the single largest gap.** Misses are concentrated
   in **vague time-of-day window encoding** (`vague_time_of_day` 48.3%, `mixed_types`
   41.7%), not in relative-date resolution: `vague_dates` (next Thursday, in two weeks)
   is 100%. Worst on Anthropic Haiku (73.0%) and GPT-4.1 mini (76.5%).
2. **Intent typing: type accuracy 94.7% (467/493).** Reminder-vs-todo and event-vs-todo
   confusion: the agent emits "set a reminder to cancel X" as a Reminder when the label
   guide makes it a Todo, and emits review/setup actions as Reminders or Events.
   Concentrated in `vague_dates` 68.8%, `type_classification` 75.0%. Worst on Anthropic
   Haiku (90.2%).
3. **Over-production hallucination: 6.5% (34/527).** The genuine signal (the matcher fix
   removed the false half): the agent fabricates an action item from a passive
   observation (`notes_only` 100%) and splits one intent into two items
   (`type_classification` 42.9%: a Reminder plus a Todo; `calendar_event_full` 20%: a
   "don't forget" Reminder on top of the Event). Worst on GPT-4.1 mini (10.8%).

**Near-solved (not primary v1 levers):**

- **Negation: 99.4% handling, 0 false positives.** One genuine miss remains: a single
  retracted reminder (`reminder_with_retraction` / synth_003) is not marked `negated`,
  on Groq only (3/10 = `negation_false_negative` 0.6% overall). Worth a negative example
  but not a headline lever.
- **Schema adherence: 100% first-attempt** (288/288). Not a lever.
- **Detection: 97.8%, Attribution: 96.8%.** Minor.

**Provider note:** Gemini 3.1 Flash Lite leads on nearly every metric (date 90.2%,
detection 100%, hallucination 2.3%, type 97.6%). Anthropic Haiku lags on date and type;
GPT-4.1 mini lags on hallucination; Groq Llama lags on detection and owns the lone
negation miss.

## Full per-metric x per-provider table (judged band, visible-24)

Score | numerator/denominator. `ALL` is the pooled micro-average.

| Metric | Anthropic Haiku | Gemini Flash Lite | Groq Llama 3.3 | GPT-4.1 mini | ALL |
|---|---|---|---|---|---|
| detection_rate | 97.6% (123/126) | 100.0% (126/126) | 95.2% (120/126) | 98.4% (124/126) | **97.8% (493/504)** |
| hallucination_rate (err) | 5.4% (7/130) | 2.3% (3/129) | 7.0% (9/129) | 10.8% (15/139) | **6.5% (34/527)** |
| type_accuracy | 90.2% (111/123) | 97.6% (123/126) | 95.0% (114/120) | 96.0% (119/124) | **94.7% (467/493)** |
| date_accuracy | 73.0% (81/111) | 90.2% (111/123) | 81.6% (93/114) | 76.5% (91/119) | **80.5% (376/467)** |
| attribution_accuracy | 97.1% (99/102) | 94.7% (108/114) | 100.0% (108/108) | 95.5% (107/112) | **96.8% (422/436)** |
| negation_handling | 100.0% (123/123) | 100.0% (126/126) | 97.5% (117/120) | 100.0% (124/124) | **99.4% (490/493)** |
| negation_false_positive (err) | 0.0% (0/123) | 0.0% (0/126) | 0.0% (0/120) | 0.0% (0/124) | **0.0% (0/493)** |
| negation_false_negative (err) | 0.0% (0/123) | 0.0% (0/126) | 2.5% (3/120) | 0.0% (0/124) | **0.6% (3/493)** |
| schema_adherence | 100.0% (72/72) | 100.0% (72/72) | 100.0% (72/72) | 100.0% (72/72) | **100.0% (288/288)** |

## Failure mode 1: date accuracy (80.5%)

Per-category, pooled providers (lowest first, denominator > 0 only; categories at 100%
omitted):

| Category | Date accuracy |
|---|---|
| mixed_types | 41.7% (15/36) |
| vague_time_of_day | 48.3% (29/60) |
| reminder_with_retraction | 57.1% (4/7) |
| negation | 58.3% (7/12) |
| type_classification | 66.7% (6/9) |
| negation_false_positive | 70.0% (7/10) |
| assignee_semantics | 80.0% (48/60) |
| self_correction_value | 83.3% (10/12) |
| multi_action | 85.0% (51/60) |
| uncertain_event | 91.7% (11/12) |
| negation_partial | 97.2% (35/36) |
| vague_dates (and 9 other categories) | 100.0% |

**Reading:** relative-date resolution (`vague_dates`: next Thursday, in about two weeks)
is perfect at 100%. The failure is vague time-of-day to fixed-window encoding (after
lunch, EOD, before I leave today, afternoon), which lives in `vague_time_of_day` and the
time-bearing items inside `mixed_types`. The labeling-guide vague-time-of-day window
table is the obvious missing piece in the prompt. `vague_time_of_day` is bad on every
provider (best is Groq at 60% on that category), so the fix is prompt-level and
provider-agnostic.

## Failure mode 2: intent typing (type accuracy 94.7%)

Per-category, pooled providers (below 100% only):

| Category | Type accuracy |
|---|---|
| vague_dates | 68.8% (33/48) |
| reminder_with_retraction | 70.0% (7/10) |
| type_classification | 75.0% (9/12) |
| negation_false_positive | 83.3% (10/12) |
| assignee_semantics | 95.2% (60/63) |

**Reading:** the agent confuses the three intent types. The pattern, confirmed on the
band pairs the judge rescued: actions framed as reminders ("set a reminder to cancel the
gym membership") are emitted as Reminders when the labeling guide makes them Todos, and
review/setup actions ("review the proposal", "set up customer interviews") are emitted as
Reminders or Events instead of Todos. This metric was partly masked at the old 0.80
cutoff (those mis-typed items were dropped as hallucinations); the judged band surfaces
them. Worst on Anthropic Haiku (90.2%).

## Failure mode 3: over-production hallucination (6.5%)

Per-category, pooled providers (above 0 only):

| Category | Hallucination rate |
|---|---|
| notes_only | 100.0% (6/6) |
| type_classification | 42.9% (9/21) |
| negation_false_positive | 33.3% (6/18) |
| calendar_event_full | 20.0% (3/15) |
| multi_action | 9.1% (6/66) |
| vague_time_of_day | 4.8% (3/63) |
| multi_item_pattern | 4.0% (1/25) |

**Reading:** two structural patterns, both real (not matcher artifacts):

- **Passive observation to action item** (`notes_only` 100%): memo_004 should produce
  only `notes`, but the agent fabricates an action item (Anthropic and OpenAI on every
  run; Gemini and Groq correctly emit nothing).
- **One intent split into multiple items** (`type_classification` 42.9%: a Reminder *and*
  a Todo for "set a reminder to cancel X"; `calendar_event_full` 20%: a "don't want to
  forget" Reminder on top of the matched Event). Worst on GPT-4.1 mini (10.8%).

## Implications for v1 (design happens next, not here)

Ranked by leverage:

1. **Encode the labeling-guide vague time-of-day window table into the prompt** (after
   lunch, EOD, before I leave, afternoon, specific windows). Largest, fully
   provider-agnostic gap. Relative-date resolution already works, so leave it alone.
2. **Sharpen intent typing**: Todo vs Reminder vs CalendarEvent rules, especially
   "remind me to {verb}" / "set a reminder to {verb}" resolves to a Todo, and
   review/setup actions are Todos not Events.
3. **Anti over-production**: a passive observation goes to `notes` with empty action
   arrays; do not emit a duplicate "don't forget" Reminder alongside an Event, and do
   not split one intent into both a Todo and a Reminder. Targets 2 and 3 are related and
   likely share prompt fixes.
4. **One negation negative example** for a retracted reminder (synth_003 / Groq), but
   negation is otherwise solved; do not over-invest.

Re-validate every number after v1 runs, and report the three slices
(visible-24 / held-out-6 / all-30) with bootstrap CIs per ADR-005.
