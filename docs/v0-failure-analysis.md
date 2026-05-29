# v0 failure-mode analysis (visible-24)

Read-only analysis of the v0 run to identify the top failure modes that drive v1 prompt design.
**No held-out data was opened or run.** This covers the visible-24 slice only, per ADR-004.

## Method

- **Source:** `test_runs` + `metric_scores` in Postgres, `agent_version = 'v0'`, `error_message IS NULL` (the 58 Groq/Gemini rate-limit marker rows are excluded; they document the rate-limit story for methodology, not scores).
- **Population:** 4 providers x 24 visible cases x 3 attempts = 288 successful runs. Every (provider, case) has exactly 3 of 3, every run has all 9 metric rows.
- **Aggregation:** micro-average, `SUM(numerator) / SUM(denominator)` per the storage design. Never `AVG(score)` (per-case denominators differ).
- **Category map:** built from `docs/test-set-composition.md` (the per-case Category column is authoritative; `memo_020 = vague_time_of_day`). Category lives in neither the transcript JSON nor the DB, so it is joined in code.
- **Empty-pool rule:** a NULL score / denominator 0 means the metric is undefined for that case and is excluded from its denominator. Shown as `n/a` below.
- **Error-direction metrics:** `hallucination_rate`, `negation_false_positive`, `negation_false_negative` are *error* rates where **lower is better** (0% = perfect). All other metrics are accuracy where higher is better.

## Headline

Two real failure modes in v0, both addressable in the prompt:

1. **Date accuracy: 79.8% (359/450).** The misses are concentrated in **vague time-of-day window encoding** (`vague_time_of_day` 48.3%, `mixed_types` 41.7%), **not** in relative-date resolution. `vague_dates` (next Thursday, in two weeks) is already at **100%**. Worst on Anthropic Haiku (72.7%) and GPT-4.1 mini (75.2%).
2. **Hallucination: 12.0% (63/527).** The agent invents action items from passive observations (`notes_only` 100%) and splits one intent into multiple items (`type_classification` 42.9%). Worst on Groq Llama (17.1%) and GPT-4.1 mini (15.1%).

**Already solved in v0 (not v1 levers, do not spend prompt budget here):**

- **Negation: fully solved.** `negation_handling` 100% (464/464), with **0 false positives and 0 false negatives** across all providers and categories. The test set was deliberately loaded toward negation / disfluency / retraction, and v0 handles all of it. (Worth re-checking on held-out-6 later, since saturation on visible could mean the cases are easy; that check happens after v1 is designed.)
- **Schema adherence: 100% first-attempt** (288/288), all providers. Not a lever.
- **Type accuracy: 97.0%**, **Attribution: 96.7%.** Minor, secondary.

**Provider note:** Gemini 3.1 Flash Lite is the v0 leader on nearly every metric (date 90.2%, detection 97.6%, hallucination 4.7%, type 100%). Anthropic Haiku and GPT-4.1 mini lag on date; Groq Llama lags on detection and hallucination.

## Full per-metric x per-provider table (micro-averaged, visible-24)

Score | numerator/denominator. `ALL` is the pooled micro-average.

| Metric | Anthropic Haiku | Gemini Flash Lite | Groq Llama 3.3 | GPT-4.1 mini | ALL |
|---|---|---|---|---|---|
| detection_rate | 92.1% (116/126) | 97.6% (123/126) | 84.9% (107/126) | 93.7% (118/126) | **92.1% (464/504)** |
| hallucination_rate (err) | 10.8% (14/130) | 4.7% (6/129) | 17.1% (22/129) | 15.1% (21/139) | **12.0% (63/527)** |
| type_accuracy | 94.8% (110/116) | 100.0% (123/123) | 97.2% (104/107) | 95.8% (113/118) | **97.0% (450/464)** |
| date_accuracy | 72.7% (80/110) | 90.2% (111/123) | 79.8% (83/104) | 75.2% (85/113) | **79.8% (359/450)** |
| attribution_accuracy | 97.0% (98/101) | 94.7% (108/114) | 100.0% (98/98) | 95.3% (101/106) | **96.7% (405/419)** |
| negation_handling | 100.0% (116/116) | 100.0% (123/123) | 100.0% (107/107) | 100.0% (118/118) | **100.0% (464/464)** |
| negation_false_positive (err) | 0.0% (0/116) | 0.0% (0/123) | 0.0% (0/107) | 0.0% (0/118) | **0.0% (0/464)** |
| negation_false_negative (err) | 0.0% (0/116) | 0.0% (0/123) | 0.0% (0/107) | 0.0% (0/118) | **0.0% (0/464)** |
| schema_adherence | 100.0% (72/72) | 100.0% (72/72) | 100.0% (72/72) | 100.0% (72/72) | **100.0% (288/288)** |

## Failure mode 1: date accuracy (79.8%)

Per-category, pooled providers (lowest first, denominator > 0 only):

| Category | Date accuracy |
|---|---|
| mixed_types | 41.7% (15/36) |
| vague_time_of_day | 48.3% (29/60) |
| reminder_with_retraction | 57.1% (4/7) |
| negation | 58.3% (7/12) |
| type_classification | 66.7% (6/9) |
| negation_false_positive | 70.0% (7/10) |
| self_correction_value | 75.0% (6/8) |
| assignee_semantics | 80.0% (48/60) |
| multi_action | 85.0% (51/60) |
| uncertain_event | 91.7% (11/12) |
| negation_partial | 97.0% (32/33) |
| **vague_dates** | **100.0% (27/27)** |
| (calendar_event_full, calendar_event_attendees, multi_item_pattern, disfluency_heavy, hallucination_trigger, reminder_pure, reminder_with_date, negation_explicit, no_date) | 100.0% |

**Key reading:** relative-date resolution (`vague_dates`: next Thursday, in about two weeks) is **perfect** at 100%. The failure is specifically **vague time-of-day to fixed-window encoding** (after lunch, EOD, before I leave today, afternoon), which lives in `vague_time_of_day` and the time-bearing items inside `mixed_types`. The labeling-guide vague-time-of-day window table is the obvious thing the prompt is missing.

Worst categories, broken down by provider:

| Category | Anthropic | Gemini | Groq | OpenAI |
|---|---|---|---|---|
| mixed_types | 33% (3/9) | 67% (6/9) | 33% (3/9) | 33% (3/9) |
| vague_time_of_day | 40% (6/15) | 40% (6/15) | 60% (9/15) | 53% (8/15) |
| type_classification | n/a | 100% (3/3) | 0% (0/3) | 100% (3/3) |
| negation | 0% (0/3) | 100% (3/3) | 33% (1/3) | 100% (3/3) |

`vague_time_of_day` is bad **everywhere** (best provider only 60%), so the fix is prompt-level and provider-agnostic, not a single weak model.

## Failure mode 2: hallucination (12.0%)

Per-category, pooled providers (highest error first, denominator > 0 only):

| Category | Hallucination rate |
|---|---|
| notes_only | 100.0% (6/6) |
| type_classification | 42.9% (9/21) |
| no_date | 33.3% (4/12) |
| negation_false_positive | 33.3% (6/18) |
| self_correction_value | 33.3% (4/12) |
| reminder_with_retraction | 30.0% (3/10) |
| vague_dates | 25.0% (12/48) |
| calendar_event_full | 20.0% (3/15) |
| multi_action | 9.1% (6/66) |
| negation_partial | 8.3% (3/36) |
| vague_time_of_day | 4.8% (3/63) |
| assignee_semantics | 4.8% (3/63) |
| multi_item_pattern | 4.0% (1/25) |
| (negation, calendar_event_attendees, uncertain_event, disfluency_heavy, hallucination_trigger, reminder_pure, negation_explicit, reminder_with_date, mixed_types) | 0.0% |

**Key reading:** two distinct patterns drive most of the hallucination.

- **Passive observation to action item** (`notes_only` 100%): the `notes_only` memo (memo_004) should produce only `notes` and empty action arrays, but the agent fabricates an action item.
- **One intent split into multiple items** (`type_classification` 42.9%): memo_019 ("set a reminder for X to cancel Y") gets emitted as both a reminder and a todo, leaving an extra unmatched item. The denominator-6 cells below (2 items per run, half unmatched) confirm double-emission.

Worst categories, broken down by provider:

| Category | Anthropic | Gemini | Groq | OpenAI |
|---|---|---|---|---|
| notes_only | 100% (3/3) | n/a | n/a | 100% (3/3) |
| type_classification | 0% (0/3) | 50% (3/6) | 50% (3/6) | 50% (3/6) |
| no_date | 0% (0/3) | 0% (0/3) | 33% (1/3) | 100% (3/3) |
| negation_false_positive | 50% (3/6) | 0% (0/3) | 50% (3/6) | 0% (0/3) |
| self_correction_value | 33% (1/3) | 0% (0/3) | 100% (3/3) | 0% (0/3) |
| vague_dates | 25% (3/12) | 25% (3/12) | 50% (6/12) | 0% (0/12) |

`n/a` for Gemini/Groq on `notes_only` means they correctly emitted **zero** action items (no denominator). Only Anthropic and OpenAI hallucinate on the notes-only memo, and they do it on **every** run (3/3). The provider spread here is wider than for date accuracy, but the two structural patterns (passive observation, intent splitting) are addressable in the prompt for all providers.

## Secondary: detection (92.1%)

Not a top-2 failure mode, but the misses are sharp and provider-specific (small N per cell):

| Category | Anthropic | Gemini | Groq | OpenAI |
|---|---|---|---|---|
| reminder_with_retraction | 100% (3/3) | 100% (3/3) | 0% (0/3) | 33% (1/3) |
| self_correction_value | 67% (2/3) | 100% (3/3) | 0% (0/3) | 100% (3/3) |
| no_date | 100% (3/3) | 100% (3/3) | 67% (2/3) | 0% (0/3) |
| vague_dates | 75% (9/12) | 75% (9/12) | 50% (6/12) | 100% (12/12) |
| assignee_semantics | 67% (12/18) | 100% (18/18) | 67% (12/18) | 100% (18/18) |

Pattern: Groq drops retracted and self-corrected items entirely; OpenAI drops the dateless todo (`no_date` 0/3). These look like model-specific recall gaps, not a shared prompt defect, so detection is a weaker v1 lever than date accuracy and hallucination.

## Implications for v1 (design happens next session, not here)

Ranked by leverage:

1. **Encode the vague time-of-day window table from the labeling guide into the prompt** (after lunch, EOD, before I leave, afternoon, specific windows). Targets the single largest, fully provider-agnostic gap. Relative-date resolution already works, so do not touch it.
2. **Anti-hallucination instructions:** (a) passive observation with no action goes to `notes` with empty action arrays; (b) one intent = one item, do not split "set a reminder to do X" into both a reminder and a todo.
3. **Leave negation, schema, type, and attribution alone.** Negation is saturated and schema is maxed; effort there is wasted.

Re-validate every number after v1 runs, and report the three slices (visible-24 / held-out-6 / all-30) with bootstrap CIs per ADR-005.
