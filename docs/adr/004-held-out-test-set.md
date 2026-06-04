# Held-out test set for v0 vs v1 comparison

**Scope:** This ADR governs the v0 -> v1 comparison only. v2 makes no generalization claim, so its held-out gate was deliberately dropped; that decision and its rationale live in `docs/v2-prompt-design.md`, not here.

When iterating from v0 to v1, designing the v1 prompt to fix specific failures observed across all 30 test cases would partially overfit v1 to those exact cases. The improvement reported in the writeup would then be a mix of real generalization and test-set memorization, and a reader could not tell how much of each. To prevent this, we split the ~30 test cases into **24 visible cases** (used for v0 evaluation, failure-mode analysis, and v1 prompt design) and **6 held-out cases** that are never inspected during v1 design.

The held-out cases are gated *mechanically*, not by discipline. v0 runs only on the visible 24 first; the held-out 6 do not get any LLM calls until after v1 is fully designed. This ensures there are no stored held-out scores to accidentally read during the iteration phase.

### Order of operations

```
1. v0  → visible 24                              (4 providers × 24 × 3 attempts = 288 calls)
2. Failure-mode analysis on v0 / visible-24 only
3. v1 prompt design (informed only by visible-24 results)
4. v1  → all 30 (visible-24 ∪ held-out-6)        (4 × 30 × 3 = 360 calls)
5. v0  → held-out 6                              (4 × 6  × 3 = 72 calls)
6. Compute and report deltas on three slices
                                                  Total: 720 calls
```

### Reporting

Every metric is reported as three v0 vs v1 deltas, each with its own 95% bootstrap CI per ADR-005:

- **Visible-24 delta** — what v1 was designed against.
- **Held-out-6 delta** — the overfitting check.
- **All-30 delta** — the headline number.

### Interpretation guide for the writeup

- If the held-out-6 delta *tracks* the visible-24 delta, v1 generalized: real improvement.
- If the held-out-6 delta *collapses* (much smaller, zero, or negative) compared to visible-24, v1 was largely overfit. The writeup must say so.
- A held-out-6 delta whose **CI straddles zero is not on its own evidence of failure to generalize.** N=6 with bootstrap CIs is intentionally noisy; ADR-005 commits us to honesty about that. The writeup's limitations section calls this out so a reader doesn't over-read a flat held-out number.

### Trade-off accepted

A final comparison on N=6 is statistically noisier than N=30 and may show a smaller or even negative delta. This is the correct trade-off because a small but methodologically clean improvement is more credible than a large overfit one.

### Locked held-out IDs

The 6 held-out cases are:

| ID | Category (primary) | Why this case |
|---|---|---|
| memo_001 | type_classification | Baseline "remind me to {verb}" → Todo case. Tests whether the type-classification rule generalizes off the visible-24 examples (memo_019 remains visible). |
| memo_005 | multi_action | Simple two-item EOD case. Tests the basic multi-action + today-window pattern off-distribution from visible-24. |
| memo_009 | vague_dates | Pure open-week window ("sometime next week"). Tests `due_date_window` generalization (memos 008, 010 remain visible). |
| memo_011 | assignee_semantics | First-person action with named recipient → `assignee = null`. Tests the baseline assignee rule (memos 012, 018 remain visible). |
| memo_016 | multi_action | Mid-complexity sprint deliverables, also exercises "remind me to send" type_classification. Tests both rules in one case. |
| memo_022 | negation_false_positive | Self-correction of value ("3, no wait, 3:30") — `negated = false`. Tests that v1 does not over-fire on negation (synth_008 remains visible). |

Every primary category in this held-out set has at least one remaining case in visible-24, so v1 prompt design has signal for each failure mode the held-out 6 exercise. The runtime gating list lives at `data/held_out_ids.txt`; the runner reads it to filter v0 / visible-24 batches.
