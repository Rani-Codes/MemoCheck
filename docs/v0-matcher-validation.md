# v0 matcher validation and the move to a judged band

Mandatory validation #1 (CLAUDE.md "Validation requirements"): manually verify the
embedding + Hungarian matcher pairings, with extra scrutiny on the hallucination
count since hallucination is one of the two headline v0 failure modes.

Read-only. No LLM calls (embeddings are local sentence-transformers per ADR-002).
Reproduce with `scripts/matcher_spotcheck.py`, `scripts/matcher_threshold_probe.py`,
and `scripts/matcher_band_probe.py`.

## Result summary

| Check | Outcome |
|---|---|
| Count reconciliation (recomputed vs Postgres) | PASS |
| 20 sampled matched pairings correct | 20 / 20 (0% error) |
| Hallucination count free of matcher artifacts | FAIL: 26 of 63 (41%) are false negatives at the 0.80 cutoff |
| Root cause | a single cosine cutoff is brittle: genuine same-item pairs whose labels differ in length or qualifiers land just under it |
| Chosen fix | replace the single cutoff with a judged band: auto-accept >= 0.80, auto-reject < 0.50, LLM judge (Claude Sonnet 4.6) decides in between (ADR-002 escalation) |

## 1. Count reconciliation: PASS

Re-running the matcher and scorer from the raw stored `expected_output` /
`actual_output` and summing independently reproduces the Postgres numbers exactly:

- detection: recomputed 464/504, Postgres 464/504
- hallucination: recomputed 63/527, Postgres 63/527

So the matcher to scorer to database wiring counts correctly. Any problem is in the
matcher's pairing decisions, not in the tallying.

## 2. Matched-pair spot-check (the mandated 20): PASS

20 randomly sampled matched (GT item, agent item) pairings (seed 0, drawn from 464
matched pairs). All 20 are the same underlying item. Lowest sampled cosine was 0.840
(`Grocery run (...)` vs `Buy eggs, milk, sourdough ...`), correctly paired. Pairing
precision on matched pairs: 0% error, well under the 5% bar.

## 3. Hallucination scrutiny: a brittle cutoff, not a wiring bug

A hallucination is an agent item the matcher leaves unmatched. The danger direction is
the cutoff being too strict: a real item scoring just under 0.80 gets dropped and
counted as a hallucination it is not, while its GT counterpart is counted as a
detection miss. This shows up as a "mutual orphan": an unmatched agent item and an
unmatched GT item that are each other's nearest neighbour at a sub-0.80 cosine.

Decomposition of the 63 hallucinations at the 0.80 cutoff:

- **37 genuine extras** (nearest GT item is already matched to a better agent item;
  Hungarian one-to-one correctly leaves this second agent item unmatched). These are
  real agent over-production: a "Don't want to forget" / "Don't be late" reminder on
  top of a matched event, one intent split into both a todo and a reminder, or an
  "auto-renews on the 20th" reminder emitted alongside the matched "Cancel gym
  membership" todo. This is the true hallucination signal.
- **26 mutual-orphan false negatives** (the agent item and its nearest GT item are both
  unmatched and are each other's nearest neighbour). These should have paired.

False-negative share: 26 / 63 = **41%**, far above the 5% escalation bar. The 9 distinct
pairs (deduped across runs), cosine 0.687 to 0.798:

| cos | case | agent item | nearest GT item |
|---|---|---|---|
| 0.798 | synth_005 | `Pick up the dry cleaning before 6pm` | `Pick up the dry cleaning` |
| 0.778 | memo_008 | `Review proposal before sending` | `Review the proposal` |
| 0.776 | memo_010 | `book the campsite` | `Book the campsite for the Lake Tahoe camping trip` |
| 0.776 | memo_002 | `pick up a new HDMI cable, probably order it online` | `pick up a new HDMI cable` |
| 0.762 | synth_007 | `Coffee meeting` | `Coffee meeting with Rebecca` |
| 0.737 | memo_018 | `Customer interviews` | `Set up customer interviews for next month` |
| 0.687 | memo_010 | `camping trip` | `Lake Tahoe camping trip` |
| 0.687 | synth_003 | `set up reminder for parents' flight` | `parents' flight lands at 9am` |

Each is the same item; the cosine is depressed only because one side carries extra
qualifiers or a longer label and ADR-002 embeds the label alone. At 0.80 the headline
hallucination rate (12.0%) is inflated and detection (92.1%) is deflated, because each
false negative is double-counted (one hallucination + one detection miss).

## 4. Why not just lower the cutoff: the cat-and-mouse problem

The obvious patch is to lower the single cutoff. The sweep shows what that buys:

| cutoff | detection | hallucination |
|---|---|---|
| 0.80 | 92.1% (464/504) | 12.0% (63/527) |
| 0.78 | 92.7% (467/504) | 11.4% (60/527) |
| 0.75 | 95.4% (481/504) | 8.7% (46/527) |
| 0.72 | 96.0% (484/504) | 8.2% (43/527) |
| 0.70 | 96.0% (484/504) | 8.2% (43/527) |
| 0.65 | 97.8% (493/504) | 6.5% (34/527) |

Every step down rescues a few more true pairs, and there is no principled place to
stop. Pick 0.80 and a real pair turns up at 0.78; pick 0.72 and the next one is at
0.68; pick 0.65 and eventually 0.60. We cannot predict the surface form of future
transcripts or the agent's phrasing, so we cannot predict the lowest cosine a genuinely
equivalent pair will take. Any fixed cutoff eventually sits above some real pair and
silently miscounts it. Re-tuning the number is a cat-and-mouse game, and the published
benchmark must not depend on a value we would have to keep chasing as the test set
grows.

## 5. The fix: a judged band (ADR-002 escalation)

Keep cosine for the easy calls and hand the ambiguous middle to an LLM judge:

- cosine >= **ceiling (0.80)**: auto-accept. Same-item reliability is high here (the
  20-pair manual check, lowest 0.840, was clean); judging it would spend tokens
  confirming the obvious.
- cosine < **floor (0.50)**: auto-reject. Obviously unrelated for this embedding model
  on short action labels; not worth a judge call.
- **floor <= cosine < ceiling**: the judge (Claude Sonnet 4.6, a non-SUT model per
  ADR-002) answers "same underlying action item?".

### Why this is not just two cutoffs instead of one

It is two edges, but their placement is the whole point. A single 0.80 cutoff sits in
the middle of the populated, ambiguous region and is guaranteed to split genuine pairs.
The band edges are placed where the data is sparse and the call is unambiguous, so a
slightly-off edge costs nothing. The assigned-pair cosine distribution across the 288
v0 runs (493 assigned pairs) makes this concrete:

| cosine band | assigned pairs |
|---|---|
| [0.00, 0.45) | 0 |
| [0.45, 0.50) | 0 |
| [0.50, 0.60) | 0 |
| [0.60, 0.70) | 9 |
| [0.70, 0.80) | 20 |
| [0.80, 1.00) | 464 |

Every assigned pair is either >= 0.80 (464, reliably same item) or in [0.60, 0.80)
(29 pairs; the 10 distinct ones are all genuine same-item pairs, cosine 0.686 to
0.798). Nothing is assigned below 0.60. So the judge owns the only populated ambiguous
region, and both band edges sit in empty space.

### Band choice: floor 0.50, ceiling 0.80

- **Floor 0.50.** It costs nothing today (zero assigned pairs in [0.50, 0.60)) and sits
  a clear margin below the lowest real pair observed (0.686) and below the entire
  occupied band. The margin is deliberate: a future genuinely-equivalent pair the
  embedder under-scores into the high 0.5s still reaches the judge rather than being
  dropped. A 0.60 floor would also work on today's data but clears the lowest real pair
  by only 0.086, so it would auto-reject a plausible future high-0.5s pair unseen,
  which is exactly the brittleness we are removing. Anywhere in [0.45, 0.60) is
  equivalent on current data; 0.50 is the defensible round midpoint and is not a tuned
  value that needs revisiting.
- **Ceiling 0.80.** Same-item above 0.80 is reliable. Knob: if a genuinely-different
  pair ever auto-accepts above 0.80, lower the ceiling so the judge vets the top band
  too. Not needed on current data.

The band edges are set in the empty regions of the distribution precisely so they do
not have to be re-tuned as the test set grows. That is the structural answer to the
cat-and-mouse concern: the only judgment that scales with new, unpredictable phrasing
is delegated to semantics, not to a number.

### Residual risk, determinism, cost

- False-reject (a genuine pair below 0.50): made unlikely by the margin; if one ever
  appears the floor drops, but the band makes that a rare, low-stakes change rather than
  a constant re-tune.
- False-accept (a genuinely different pair above 0.80): not observed; mitigated by
  lowering the ceiling if needed.
- Determinism: scoring is no longer purely deterministic. Mitigated by running the judge
  at temperature 0 and caching each verdict on (model, gt_text, agent_text) so re-runs
  are stable and never re-pay. ADR-002's "deterministic" claim gets a caveat.
- Cost: bounded. On v0 the band holds 10 distinct pairs, so the re-score is about 10
  unique judge calls (cached across the 288 runs). Later v1 / held-out runs add only
  their new distinct band pairs. The CLAUDE.md cost-table "LLM-as-judge = $0" line is
  updated accordingly.

This reasoning (the cat-and-mouse argument and the band-placement principle) is to be
surfaced in the README methodology section at writeup time, per the project author's
request.

## Required follow-up

1. Implement the judged band: add a `judge` hook to `match()` with ceiling 0.80 (the
   existing `DEFAULT_THRESHOLD`) and a new `DEFAULT_JUDGE_FLOOR = 0.50`; add
   `evals/judge.py` (Claude Sonnet 4.6, temperature 0, verdicts cached and persisted).
2. Re-score the 288 stored v0 runs from `actual_output` / `expected_output` with the
   judge enabled and refresh the matcher-derived `metric_scores` (schema_adherence is
   not matcher-derived and is left untouched). No new extractor calls.
3. Update ADR-002 (record the judge model, the band edges, and the determinism caveat),
   the "0.8 cosine-similarity threshold" references in CLAUDE.md, the cost table, and
   re-add the judge-model config to `.env.example`.
4. Revise `docs/v0-failure-analysis.md` with the re-scored detection / hallucination /
   date numbers. Date accuracy is computed on matched pairs and shifts only for the few
   newly-matched pairs; the two headline failure modes still stand (date accuracy is the
   largest; over-production hallucination, the 37 genuine extras, is real at roughly 8%),
   but the magnitudes change.
