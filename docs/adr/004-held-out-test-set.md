# Held-out test set for v0 vs v1 comparison

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
