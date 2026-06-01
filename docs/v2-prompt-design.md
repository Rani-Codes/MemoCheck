# v2 agent prompt design

Date: 2026-06-01
Status: approved in a grilling session (grill-with-docs).
What this produces: `src/memocheck/agent/prompts/v2.py`, which exports `SYSTEM_PROMPT`.

## What we're doing and why

v1 did its job on two of v0's gaps: it moved type accuracy (0.958 -> 0.997, CI excludes
zero) and hallucination (0.057 -> 0.023). But it left the single biggest gap, date accuracy,
flat in aggregate: all-30 went 0.772 -> 0.795 with a 95% CI of [-0.056, +0.112], which
straddles zero. That is the one thing v2 fixes. Nothing else.

The reason the date aggregate stayed flat is not that v1 did nothing to dates. v1 won one
date slice big (vague times of day) but introduced offsetting date regressions on other
cases, so the two cancelled out. v2's whole job is to remove the cause of those regressions
without giving back the win.

We keep the change as small as v1 kept its change, and for the same reason: so the v1 -> v2
delta is cleanly attributable to the date fix alone. v2 edits only the date section of the
prompt. It does not touch type, hallucination, negation, assignee, or the worked examples.

This doc is just the plan. We don't run the model or spend any API tokens here.

A note on the held-out set: for v0 -> v1 we kept 6 cases unseen (ADR-004) so the
generalization claim was honest. For v2 that gate is dropped, so all 30 cases were visible
during this design. That means overfitting is now the top risk, and we guard against it the
only way that survives having seen the data: every change below is either a deletion that
reverts to known-good v0 behavior, or a single general principle that restores behavior v0
already had. Nothing is tuned to a specific case, and no example is copied from the 30.

## What this is based on

- `docs/v1-prompt-design.md`: the v1 design. v2 mirrors its structure and extends v1 the
  same way v1 extended v0.
- `src/memocheck/agent/prompts/v1.py`: the current prompt. v2 builds on it. Its date rules
  are Section 1 (1a vague-time-of-day table, 1b before/by/after weekday).
- `docs/labeling-guide.md`: the source of truth for date rules (sections 5, 6, 7).
- A read-only diagnostic over the restored Postgres backup: per-case v0 vs v1
  `date_accuracy` / `type_accuracy` / `detection_rate` counts, plus the actual emitted
  datetimes on the regressed cases. The numbers below come from it.
- `docs/adr/003-*` (naive local datetimes, scorer localizes), `004-*` (held-out),
  `005-*` (bootstrap CIs).

## What v1 did to dates (the diagnosis)

`date_accuracy` is scored only on type-matched pairs (see `scorer.py`: `date_pair_count`
counts a pair only when the agent's type matches ground truth's). So a date score can move
for three reasons: the agent emitted a different date (a real date-value change), the set of
type-matched pairs shifted (a type or matching change pulling pairs in or out of the date
pool), or temperature-0 run-to-run noise. The diagnostic separates these by watching the
denominator.

### The win to protect: rule 1a (vague time of day)

memo_020 (every vague-time phrase in one memo) went `date_accuracy` 0.48 -> 0.89. This is the
v1 date win, and it comes entirely from the 1a time-of-day table. v2 leaves 1a completely
alone.

### Bleed A: rule 1b shifts weekday references one day forward

1b ("before / by / after a weekday") makes the weakest model (Anthropic Haiku) shift any
weekday-anchored date forward by one calendar day, even when there is no before/by/after
qualifier at all. The denominators are stable on these cases, so this is a genuine
date-value change, not a matching artifact:

| Case | Phrase | GT | v0 (correct) | v1 (shifted) |
|---|---|---|---|---|
| memo_007 | "Friday at 2pm" (plain event) | Fri 05-29 14:00 | 05-29 | **05-30** |
| synth_004 | "Thursday at 2pm" (event) | Thu 05-28 14:00 | 05-28 | **05-29** |
| synth_007 | "Thursday at 9am" (event) | Thu 05-28 09:00 | 05-28 | **05-29** |
| synth_006 | "by Friday" (deadline) | Fri 05-29 23:59 | 05-29 | **05-30** |

memo_013 ("Monday at 9am") regressed in the same direction and is consistent with the same
shift. Every case above states an explicit weekday with an explicit time and no before/by/after
word, so 1b should not touch them; its mere presence makes the model over-eager to shift.
synth_006 is worse: "by Friday" should stay on Friday, but the model applied the "after" shift.

The damning part: **1b earned nothing on its own flagship target.** memo_006 ("pay the credit
card bill before Friday", the canonical before-weekday deadline that 1b was written to fix)
stayed at `date_accuracy` 0.42 in both v0 and v1. The model ignores the "before" rule even
when it is present. So 1b is pure cost, no benefit.

### Bleed B: vague relative date resolves to null

v1 made the model stop committing a concrete date for vague future references that v0 had
resolved fine, emitting `due_date: null` instead. Denominators stable, so again a real
value change:

| Case | Phrase | GT window | v0 (correct) | v1 |
|---|---|---|---|---|
| memo_009 | "sometime next week" | 06-01 .. 06-07 | 06-05 | **null** (anthropic + gemini) |
| memo_010 | "in about two weeks" | end 06-09 | 06-09 | **null** (gemini, todo only) |

The "resolve relative references like next Thursday or in two weeks" line exists in both v0
and v1, so the instruction did not change. The most likely mechanism: v1's expanded,
table-heavy date section taught the model "if the phrase isn't in one of my lookup tables,
leave it null." The vague relative phrases ("next week", "a couple weeks") match no table,
so the model defaulted to null.

### Set aside as out of scope (v1 residuals, not v2's job)

- synth_004 type accuracy dropped 12 -> 10 (a type change, not a date change).
- memo_010 detection dropped 24 -> 21 (a matching change).
- openai shows pre-existing run-to-run instability on synth_007 (06-04 in both v0 and v1),
  i.e. it picks the wrong Thursday regardless of version. Not a v1 regression.

These live in rules v2 does not touch, so they sit at the same level on both sides of the
v1 -> v2 comparison. See "Not part of v2."

## The approach we picked: keep v1, remove what backfired, restore what regressed

Keep all of v1 exactly as it is, except the date section. There, make two changes: delete
rule 1b, and add one line that restores v0's commit-a-date behavior for vague relative
references.

We looked at three other options and passed:

- **A guardrail instead of deleting 1b** (a line saying "a weekday with a time is that exact
  weekday, never shift it"). Passed: v0 had no such line and got every clean weekday case
  right, so the guardrail is dead weight. The cleaner story is "the rule backfired, we
  removed it."
- **Also fixing the type / detection residuals** (synth_004, memo_010). Passed: they are N=1
  dips in metrics already at the ceiling (type ~0.997, hallucination ~0.023), and fixing them
  means reopening the Section 2/3 rules that v1 got right, risking a new regression for a
  one-case gain. It would also break the clean "we changed only dates" attribution.
- **Teaching the section-6 week-window math for Bleed B** (Monday-to-Sunday boundaries,
  etc.). Passed: that is the over-engineering the v1 design already rejected, and with all 30
  cases visible it is the most overfitting-prone move. A single "commit to a date inside the
  period" principle is enough to land inside the window, and it is robust rather than tuned.

## Decisions we've locked in

- Delete rule 1b in full (all three lines: before / by / after). No guardrail.
- Add exactly one reinforcement line for Bleed B, and preserve the "no time mentioned -> null"
  boundary so it cannot make the model hallucinate a date on genuinely dateless cases.
- Rule 1a (the time-of-day table) is untouched, including "early/late {X}" and
  "tomorrow afternoon = 15:00".
- No new worked examples. Keep v1's four exactly as they are.
- The synth_004 type drop and the memo_010 detection drop are left as documented residuals.
- Net change to the date section: minus 4 lines (1b), plus 1 line (Bleed B).

## The plan, section by section

### Section 0: what we keep from v1 untouched

Everything except the two date-section edits below. That includes: the intro line, the
`{current_date}` placeholder, the four category definitions, the JSON template, the
"JSON only, no markdown" instruction, the full type-classification rules, the "one thing said
= one item" rules, the assignee rules, the grocery-list rule, the negation rules, the 1a
vague-time-of-day table, the surviving "resolve relative references like next Thursday / in
two weeks" line, the "date only, no time -> 23:59" line, the "no date or time -> null" line,
and all four worked examples.

### Section 1: the date fix

**1.1 Delete rule 1b (the weekday block).** Remove these four lines from v1's date section:

```
- For a deadline tied to a weekday:
  - "before {weekday}" -> the day BEFORE that weekday at 23:59 ("before Friday" -> Thursday 23:59)
  - "by {weekday}" / "no later than {weekday}" -> that weekday at 23:59
  - "after {weekday}" -> the day AFTER that weekday at 00:00
```

After deletion, nothing in the date section mentions shifting a weekday, so the cue that
caused Bleed A is gone. The weekday cases revert to v0's rule-free behavior, which was
correct on all of them. The one genuinely-hard case (memo_006 "before Friday") was already at
0.42 in v0, and 1b never moved it, so removing the rule is neutral there and a clear win
everywhere else.

**1.2 Add one line for Bleed B.** Add this single line directly after the existing
"resolve relative references" line, leaving that line word-for-word unchanged:

> For a vague future reference (for example "sometime next week" or "in a couple weeks"),
> still commit to a single concrete date inside that period; a day comfortably in the middle
> of it is safe. Only leave the date null when the transcript gives no time reference at all.

This restores the behavior v0 already had (committing a date that lands inside the labeling
guide's section-6 window) and that v1 regressed away. It teaches no window boundaries, so it
is robust rather than tuned. The final clause keeps the "no time mentioned -> null" boundary
intact, so it will not push the model to invent dates on the genuinely dateless cases like
memo_002. It mirrors 1a's existing "pick the middle of the range" philosophy.

## Things we must not break

- Rule 1a's win (memo_020 ~0.89). Deleting 1b must not touch the time-of-day behavior.
- First-attempt schema adherence stays at 100% (v0 and v1 both clean). This is why v2, like
  v1, stays rules-only with no reasoning / scratchpad field: a free-text field risks the
  weaker models writing outside the JSON.
- The agent keeps outputting naive local wall-clock datetimes; the scorer does the timezone
  math (ADR-003). The agent never reasons about UTC.
- Output matches `ExtractedMemo`: empty lists not nulls, one model call, temperature 0, raw
  JSON only.
- v2 lives at `src/memocheck/agent/prompts/v2.py`, exports `SYSTEM_PROMPT`, and keeps the
  `{current_date}` placeholder (the extractor fills it in).
- Type, hallucination, negation, detection stay stable. v2 edits only the date section, so
  they should not move; the run confirms there were no side effects.

## How we'll check v2 (later, not now)

- Score v1 and v2 the exact same way: the same judged matcher band and the same persisted
  judge cache (`data/judge_cache.json`), or the comparison mixes up "the agent changed" with
  "the scoring changed".
- Run v2 on all 30 cases (4 x 30 x 3 = 360 calls). v0 and v1 already have all-30 data in
  Postgres. The comparison is v1 vs v2.
- Report the all-30 `date_accuracy` delta with a 95% bootstrap CI (ADR-005). Because v2 was
  designed with all 30 cases visible, the visible-24 / held-out-6 split is informational only
  for v2; it is no longer a clean generalization test the way it was for v0 -> v1. The
  defense against overfitting is the qualitative one stated up top (deletion plus one general
  principle), not the held-out slice.
- The report code currently hardcodes the v0/v1 pair; emitting `v1_vs_v2.json` needs the
  deferred `--baseline/--candidate` generalization (a tdd job on the report step, the DB is
  already version-agnostic). Not part of this design.
- That run costs tokens, so we get explicit go-ahead first.

**Success criterion (and stopping point).** Stop here and move on to the report and dashboard
if both hold:

1. all-30 `date_accuracy` moves clearly positive, out of v1's flat [-0.056, +0.112] band, and
2. the guard metrics (type, hallucination, negation, detection, schema adherence) do not
   regress.

The prediction is a strong bet because we are reverting to known-good v0 behavior on Bleed A
and restoring documented v0 behavior on Bleed B, not inventing anything. v2 is intended as
the final agent iteration for this project. If the run does not move the aggregate positive,
that is itself an honest, reportable finding; reassess then rather than auto-spawning a v3.

The narrative this completes: v0 -> v1 fixed type and hallucination and won vague times of
day, but the date aggregate stayed flat because a new weekday rule backfired. The
per-category breakdown surfaced that masked regression, we diagnosed it, and v2 removed the
backfiring rule and restored the vague-relative commit, so the date gap finally moves. That
detect-diagnose-fix loop is the project's thesis.

## Not part of v2

- The synth_004 type drop and the memo_010 detection drop (documented residuals; out of
  scope, left at v1 levels).
- Making "before / by / after a weekday" deadlines work (memo_006 stays unsolved at ~0.42;
  1b did not help it, so deleting 1b is neutral there). Future work if revisited.
- The section-6 week-window math, a reasoning / scratchpad field, and any change to the
  scorer, the schema, or the extractor. v2 is only a prompt change.
