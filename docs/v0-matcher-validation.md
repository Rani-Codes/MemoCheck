# v0 matcher validation and threshold calibration

Mandatory validation #1 (CLAUDE.md "Validation requirements"): manually verify the
embedding + Hungarian matcher pairings, with extra scrutiny on the hallucination
count since hallucination is one of the two headline v0 failure modes.

Read-only. No LLM calls (embeddings are local sentence-transformers per ADR-002).
Reproduce with `scripts/matcher_spotcheck.py` and `scripts/matcher_threshold_probe.py`.

## Population

288 v0 runs on the visible-24 slice (4 providers x 24 cases x 3 attempts),
`error_message IS NULL`. Held-out 6 not touched.

## Result summary

| Check | Outcome |
|---|---|
| Count reconciliation (recomputed vs Postgres) | PASS |
| 20 sampled matched pairings correct | 20 / 20 (0% error) |
| Hallucination count free of matcher artifacts | FAIL: 26 of 63 (41%) are false negatives |
| Root cause | 0.8 cosine threshold too strict for label length / qualifier differences |
| Recommended fix | lower threshold to 0.72, re-score from stored outputs (no token spend) |

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

## 3. Hallucination scrutiny: FAIL (matcher too strict)

A hallucination is an agent item the matcher leaves unmatched. The danger direction
is the matcher being too strict: a real item scoring just under 0.8 gets dropped and
counted as a hallucination it is not, while its GT counterpart is counted as a
detection miss. This shows up as a "mutual orphan": an unmatched agent item and an
unmatched GT item that are each other's nearest neighbour at a sub-0.8 cosine.

Decomposition of the 63 hallucinations at the live 0.80 threshold:

- **37 genuine extras** (nearest GT item is already matched to a better agent item;
  Hungarian one-to-one correctly leaves this second agent item unmatched). These are
  real agent over-production: a "Don't want to forget" / "Don't be late" reminder on
  top of a matched event, or one intent split into both a todo and a reminder, or an
  "auto-renews on the 20th" reminder emitted alongside the matched "Cancel gym
  membership" todo. This is the true hallucination signal.
- **26 mutual-orphan false negatives** (the agent item and its nearest GT item are
  both unmatched and are each other's nearest neighbour). These should have paired.

False-hallucination share: 26 / 63 = **41%**, far above the 5% escalation bar.

The 9 distinct false-negative pairs (deduped across runs), cosine 0.687 to 0.798:

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

Every pair down to 0.737 is unambiguously the same item; the cosine is depressed only
because one side carries extra qualifiers or a longer label and ADR-002 embeds the
label alone. The two 0.687 pairs are genuinely borderline (a short event title, and a
retracted reminder reframed as a follow-up todo).

Consequence: at 0.80 the headline hallucination rate (12.0%) is inflated and the
detection rate (92.1%) is deflated, because each false negative is double-counted (one
hallucination + one detection miss). Both numbers in `docs/v0-failure-analysis.md` are
affected. Date accuracy is computed on matched pairs only and is affected only by the
small set of pairs that newly match.

## 4. Threshold sweep

Detection and hallucination micro-totals over the same 288 runs:

| threshold | detection | hallucination |
|---|---|---|
| 0.80 (live) | 92.1% (464/504) | 12.0% (63/527) |
| 0.78 | 92.7% (467/504) | 11.4% (60/527) |
| 0.75 | 95.4% (481/504) | 8.7% (46/527) |
| 0.72 | 96.0% (484/504) | 8.2% (43/527) |
| 0.70 | 96.0% (484/504) | 8.2% (43/527) |
| 0.65 | 97.8% (493/504) | 6.5% (34/527) |

## 5. Does lowering introduce wrong matches? No.

The distinct new matches created by going from 0.80 to 0.70 (the loosening-risk
check) are exactly these 7, and all 7 are correct same-item pairs:

```
0.798  GT(todo)  'Pick up the dry cleaning'                     <-> AG(todo)     'Pick up the dry cleaning before 6pm'
0.778  GT(todo)  'Review the proposal'                          <-> AG(reminder) 'Review proposal before sending'
0.776  GT(todo)  'pick up a new HDMI cable'                      <-> AG(todo)     'pick up a new HDMI cable, probably order it online'
0.776  GT(todo)  'Book the campsite for the Lake Tahoe ...'      <-> AG(todo)     'book the campsite'
0.762  GT(event) 'Coffee meeting with Rebecca'                   <-> AG(event)    'Coffee meeting'
0.737  GT(todo)  'Set up customer interviews for next month'     <-> AG(event)    'Customer interviews'
```

Zero wrong matches are introduced. (Negation pairs like "buy milk" vs "don't buy milk"
are intentionally allowed to match for detection; negation is scored separately on the
`negated` flag per ADR-002, so a lower threshold does not harm negation scoring.)

## Recommendation

Lower the matcher threshold from 0.80 to **0.72**. At 0.72:

- detection 92.1% to 96.0%, hallucination 12.0% to 8.2%
- 20 of the 26 false-negative hallucinations are rescued, zero wrong matches created
- the 6 remaining orphans are the two genuinely borderline 0.687 pairs, which it is
  defensible to leave unmatched

This is a proportionate fix: the failures are a clean cluster of true same-item pairs
sitting just under the old threshold, and the genuine-extra hallucinations (which are
protected by one-to-one assignment, not the threshold) are unaffected. The remaining
8.2% hallucination is the real over-production signal for v1 to target.

### Alternative (ADR-002's stated escalation)

ADR-002 prescribes a hybrid top-K + LLM-judge fallback if the spot-check fails. That is
heavier, costs tokens, and re-introduces an LLM judge the project deliberately kept out
of the core scoring path. The evidence here points to simple threshold miscalibration
rather than a need for semantic judging, so threshold recalibration is the lighter and
more defensible fix. If chosen, ADR-002 and the CLAUDE.md threshold references should be
updated to record the deviation and its rationale.

## Required follow-up once a threshold is chosen

1. Update `DEFAULT_THRESHOLD` in `src/memocheck/evals/matcher.py`.
2. Re-score all stored v0 runs from `actual_output` / `expected_output` and refresh
   `metric_scores` (no LLM calls; raw outputs are already persisted).
3. Update ADR-002 and the "0.8 cosine-similarity threshold" references in CLAUDE.md.
4. Revise `docs/v0-failure-analysis.md` with the re-scored detection / hallucination /
   date numbers. The two headline failure modes still stand (date accuracy is the
   largest; over-production hallucination is real at ~8%), but the magnitudes change.
