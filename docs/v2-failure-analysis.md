# v2 failure-mode analysis (all-30)

Analysis of the v1 -> v2 run. v2's one job was to move date accuracy off v1's
flat band without regressing anything else (see `docs/v2-prompt-design.md`). It did not.
This doc records why, and the more important conclusion underneath it: **at this test-set
size, date accuracy is sample-size-bound, so a single-line prompt edit cannot produce a date
delta we can distinguish from the test set's case-sampling variance** (the dominant of two
measured noise floors, kept separate below).

Per ADR-004, the held-out gate was dropped for v2, so all 30 cases were visible during
design. The comparison here is v1 (baseline) vs v2 (candidate) on all 30.

**Scoring note:** these numbers use the same judged-band matcher (auto-accept cosine
`>= 0.80`, auto-reject `< 0.50`, Claude Sonnet 4.6 judges in between) and the same persisted
judge cache (`data/judge_cache.json`) as the v0 and v1 scores. v1 and v2 are scored
identically, so every movement below is an agent change, not a scoring change (ADR-002).

## Method

- **Source:** `test_runs` + `metric_scores` in Postgres, `agent_version IN ('v1','v2')`,
  `error_message IS NULL`. 4 providers x 30 cases x 3 attempts = 360 runs per version.
- **Aggregation:** micro-average, `SUM(numerator) / SUM(denominator)`. Never `AVG(score)`.
- **Category / provider maps:** built from `docs/test-set-composition.md`, joined in code.
- **CIs:** 95% bootstrap, 1000 resamples, seed 0, from `data/results/v1_vs_v2.json` (ADR-005).
- **Error-direction metrics:** `hallucination_rate` and the two negation error rates are
  *error* rates (lower is better); all others are accuracy (higher is better).

## Headline

1. **v2 missed its success criterion.** all-30 `date_accuracy` went **0.795 -> 0.766**
   (delta **-0.030**, 95% CI **[-0.086, +0.026]**). The target was "clearly positive, out of
   v1's flat band." It moved the wrong way and the CI still straddles zero.
2. **No guard metric regressed beyond noise.** type, hallucination, detection, attribution,
   negation, and schema adherence all sit within a CI that includes zero. So v2 is not
   *broken*; it is *inert plus a little wander*.
3. **The real finding: the date gap is sample-size-bound at N=30.** Across all three versions
   the aggregate has only ever moved inside a 0.77 to 0.80 band (v0 0.772, v1 0.795, v2 0.766).
   The date deltas are small, consistent shifts (v0 -> v1 +0.024, v1 -> v2 -0.030) that
   *survive* run-to-run nondeterminism but sit well *inside* the case-sampling confidence
   interval. There are two independent noise floors here; the date deltas clear the smaller
   one and are swallowed by the larger. The next section measures both, separately.

## Aggregate result (all-30, v1 vs v2)

| Metric | v1 | v2 | delta | 95% CI | read |
|---|---|---|---|---|---|
| date_accuracy | 0.795 | 0.766 | **-0.030** | [-0.086, +0.026] | target metric, moved wrong way, CI straddles 0 |
| type_accuracy | 0.997 | 0.992 | -0.005 | [-0.016, +0.000] | within noise |
| hallucination_rate (err) | 0.023 | 0.027 | +0.005 | [-0.000, +0.012] | within noise |
| detection_rate | 0.966 | 0.973 | +0.006 | [0.000, +0.015] | within noise |
| attribution_accuracy | 0.981 | 0.979 | -0.002 | [-0.007, +0.000] | within noise |
| negation_handling | 1.000 | 1.000 | 0.000 | [0, 0] | flat |
| schema_adherence | 1.000 | 1.000 | 0.000 | [0, 0] | flat, 360/360 first-attempt |

## The two noise floors (kept separate)

A metric delta is only a credible, generalizable improvement if it clears two *independent*
sources of variance. We measure them separately and do not conflate them. Both numbers come
from data already in Postgres; no new runs.

**Floor 1, run-to-run nondeterminism.** How much a score wobbles when the *identical* input
is re-run at temperature 0. Measured directly from the 3 attempts per (version, provider,
case): within a version the prompt and the cases are fixed, so attempt-to-attempt movement is
pure provider serving nondeterminism. All-30 `date_accuracy` by single attempt:

| version | att 1 | att 2 | att 3 | spread |
|---|---|---|---|---|
| v0 date | 0.7744 | 0.7704 | 0.7704 | 0.004 |
| v1 date | 0.7861 | 0.7960 | 0.8040 | **0.018** |
| v2 date | 0.7650 | 0.7696 | 0.7626 | 0.007 |

At the cell level, **15 of 346** (version, provider, case) cells return a different date
score across their 3 attempts, and when a cell varies it varies hard (mean spread 0.58, max
1.0). Pooled to the all-30 aggregate these partly cancel, leaving a run-to-run floor of about
**0.004 to 0.018** on date. The same floor on type and hallucination is smaller (~0.005 to
0.009), which matters below.

**Floor 2, case-sampling variance.** How much a score would wobble if a *different* 30
transcripts had been drawn. This is the 95% bootstrap CI (1000 resamples, seed 0, ADR-005).
On the v1 -> v2 date delta it is **[-0.086, +0.026], about ±0.06**, far wider than Floor 1,
because 30 cases is a small sample.

These are complementary and independent: Floor 1 is a property of the models, Floor 2 is a
property of the test set. A delta has to clear *both* to count.

### Where the date deltas land

| date delta | size | vs Floor 1 (~0.018) | vs Floor 2 (~±0.06) |
|---|---|---|---|
| v0 -> v1 | +0.024 | clears it | **inside it** |
| v1 -> v2 | -0.030 | clears it | **inside it** |

So the precise statement, narrower than "it is all rerun jitter": the date deltas are small,
consistent shifts that **survive run-to-run noise but are dominated by case-sampling
variance**. The binding constraint is Floor 2, the test-set size, not nondeterminism. Date is
sample-size-bound, not prompt-fixable-and-measurable at N=30.

### Why the type and hallucination wins are trustworthy and date is not

The same per-attempt view cleanly separates real signal from noise. For a v0 -> v1 win to be
real, every v1 rerun should beat every v0 rerun (Floor 1 cleared) *and* the CI should exclude
zero (Floor 2 cleared):

| metric | v0 attempt range | v1 attempt range | ranges overlap? | v0 -> v1 CI excludes 0? |
|---|---|---|---|---|
| type_accuracy | 0.952 to 0.961 | 0.995 to 1.000 | no, gap +0.034 | yes |
| hallucination (err) | 0.051 to 0.060 | 0.019 to 0.024 | no, clean gap | yes |
| date_accuracy | 0.770 to 0.774 | 0.786 to 0.804 | barely, +0.012 | no |

Type and hallucination clear **both** floors: their v0 and v1 attempt ranges are disjoint by a
wide margin, and their bootstrap CIs exclude zero. That is why they are the project's
trustworthy result. Date clears only Floor 1, and only barely, then dies under Floor 2.

### Supporting observation: the providers disagree on the sign

Consistent with date being noise rather than signal, the four providers do not move together
on the v1 -> v2 date delta:

| provider | v1 date | v2 date | delta |
|---|---|---|---|
| anthropic | 0.687 (103/150) | 0.735 (108/147) | **+0.048** |
| gemini | 0.904 (141/156) | 0.846 (132/156) | -0.058 |
| groq | 0.847 (127/150) | 0.763 (116/152) | -0.084 |
| openai | 0.738 (107/145) | 0.714 (105/147) | -0.024 |

A real prompt-level effect would push the four models in one direction. Instead one rises and
three fall by differing amounts, and the denominators drift as the type-matched date pool
shifts (anthropic 150 -> 147, groq 150 -> 152). That is per-model wander on a shared prompt.
As a per-case illustration of the same instability: memo_020, a rule-1a case whose governing
prompt text is byte-for-byte identical in v1 and v2, still swung 50/56 -> 56/56 (+0.107 on
that case) purely from the surrounding run, not from any rule that changed.

## What the two edits actually did (the diagnosis)

Even when we decompose v2 into its two intended edits, each effect is a handful of items,
the same order as the per-case noise in section B. Neither is large enough to clear it.

### The vague-relative line (Bleed B fix): net positive, one casualty

The added line ("for a vague future reference still commit to a single concrete date inside
that period; only leave null when there is no time reference at all") was a net win on its
target, and it broke exactly one case:

| case | phrase | v1 | v2 | effect |
|---|---|---|---|---|
| memo_009 | "sometime next week" | 3/12 | 12/12 | +9 (fixed v1's null regression) |
| memo_010 | "in about two weeks" | 18/21 | 23/23 | +5 (same) |
| memo_015 | "maybe Tuesday" (uncertain) | 12/12 | 3/12 | **-9 (overreach)** |

memo_015's ground truth deliberately carries `due_date: null` (the followup "check with the
office" has no stated deadline; the hedge "maybe Tuesday" belongs in `notes`). The new line's
escape clause ("only null when there is no time reference at all") does not fire here,
because the transcript *does* contain a time reference. Confirmed in the emitted output:

| version | leaves due_date null (correct) | commits a date (wrong) |
|---|---|---|
| v1 | all 4 providers, 12/12 | none |
| v2 | anthropic only, 3/12 | gemini `2026-06-02T23:59`, openai `2026-06-02T23:59`, groq `2026-05-27T17:00` |

So this edit traded a fix on two vague-relative cases for a regression on one uncertain-event
case. Net positive in aggregate, but all three are single cases at denominator 12.

### Deleting rule 1b: the Bleed A theory was half-wrong

v2 deleted the before/by/after-weekday block (1b) on the theory that it made Anthropic Haiku
shift weekday-anchored dates forward by a day. Removing it was supposed to revert the weekday
cases to v0-correct. The data shows the opposite: **every weekday case got worse without 1b.**

| weekday case | v1 (1b present) | v2 (1b deleted) |
|---|---|---|
| memo_006 "before Friday" | 15/36 | 12/36 |
| memo_007 "Friday at 2pm" | 9/12 | 6/12 |
| synth_003 "Saturday..." | 12/12 | 9/12 |
| synth_004 "Thursday at 2pm" | 6/10 | 3/10 |
| synth_007 "Thursday at 9am" | 6/12 | 3/12 |

The diagnosis correctly observed Haiku mis-shifting under 1b, but missed that 1b was *net
helping* the other three models anchor weekday deadlines. Deleting it removed a net-positive
rule to fix a single-model symptom. This is why anthropic was the one provider that improved
in section C (it lost the bad shift) while the other three lost the good anchoring.

The two edits roughly cancel: the vague-relative line nets a few items up, the 1b deletion
nets several items down, and the remainder is run-to-run wander. The aggregate lands a hair
below v1, well inside the CI.

## Conclusion and implications

- **The date gap is real but sample-size-bound at this N.** It has sat in a 0.77 to 0.80
  band across v0, v1, and v2. The misses are genuine (vague time-of-day windows, weekday
  deadlines, the occasional wrong-week resolution), but the per-edit effect (~0.03) is
  smaller than the case-sampling floor (Floor 2, ~±0.06), so we cannot attribute movement to
  a fix with any confidence. Run-to-run nondeterminism (Floor 1, ~0.018) is a second, smaller
  floor underneath it; the date deltas clear Floor 1 but not Floor 2.
- **v1 remains the hero result.** Its wins were real because they were large enough to clear
  the noise: type accuracy 0.958 -> 0.997 and hallucination 0.057 -> 0.023, both with CIs
  that exclude zero. Date was already flat at v1 ([-0.056, +0.112]); v2 confirms that
  flatness is structural, not a v1 accident.
- **v2 is the honest negative, and it is reportable as one.** Per its own stopping rule
  (`docs/v2-prompt-design.md`), a non-positive aggregate is a finding, not a trigger for a
  v3. The detect-diagnose loop did its job: it surfaced that v1's flat date number hid
  offsetting per-case and per-model effects, and that a carefully reasoned single-line fix
  gets swallowed by the same variance.
- **What would actually be needed to move date credibly** (all out of scope here, future
  work): a larger and more date-dense test set so per-case denominators can resolve a
  sub-5-point effect, or per-model handling, which is exactly the fragile tuning this project
  avoids on purpose. The robust read is to report the gap honestly with its CI rather than
  chase it with prompt edits the test set cannot measure.

The narrative this completes: v0 -> v1 fixed type and hallucination decisively (both clearing
both noise floors) and left date flat. v2 set out to move date, and instead demonstrated
*why* date stays flat: at 30 cases the metric is sample-size-bound, so the small shifts any
prompt change produces, in either direction, fall inside the case-sampling confidence
interval. That is the project's most honest result about the hardest part of the task, and it
is a finding about the benchmark's resolution, not just the agent.
