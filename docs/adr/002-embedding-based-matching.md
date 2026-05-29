# Embedding-based matching with Hungarian algorithm

Flattened detection (see ADR-001) requires pairing ground-truth items with agent output items before scoring. We use `sentence-transformers` embeddings to compute pairwise cosine similarity, then the Hungarian algorithm to find the optimal one-to-one pairing above a 0.8 cosine-similarity threshold. This is deterministic, free, and fast. The known weakness -- embeddings missing nuance like negation ("buy milk" vs "don't buy milk") -- is handled separately by the schema's `negated: bool` flag, which the agent populates directly.

### What gets embedded

The embedding input is **just the natural-language label** of each item -- `description` for `TodoItem` and `Reminder`, `title` for `CalendarEvent`. Type tokens (`"todo:"`, `"event:"`), dates, assignees, and attendees are deliberately **not** included in the embedded string. Three reasons:

1. **Type-agnostic by design.** Tier 1 (detection) is intentionally flattened across todos/reminders/events; Tier 2 (type accuracy) scores the type separately. If we put type info into the embedded string, the matcher would learn to refuse to pair a `Todo("call dentist")` with a `CalendarEvent("call dentist")` even though those should match for detection purposes and *fail* at Tier 2.
2. **Date and people fields are scored at Tier 3.** Mixing them into the matching signal would conflate detection with field accuracy, which is exactly the double-penalty problem ADR-001 set out to fix.
3. **The label carries 95%+ of the semantic signal.** Adding more text to short labels tends to dilute the cosine distance rather than sharpen it.

The matcher itself ignores type information, but the scorer needs to recover it after matching. The implementation flattens to tuples like `(embedded_text, item_type, original_object)` so Tier 2/3 can read the type and full object back off the matched pair.

This choice also eliminates self-preference bias from the core metrics: by using deterministic scoring throughout (embeddings for matching, field comparison for everything downstream), no LLM-as-judge is invoked during evaluation. If the manual spot-check shows the matcher is wrong on more than 5% of cases, we will escalate to a hybrid approach (embeddings narrow to top-K candidates, an LLM judges among those) -- and any LLM judge introduced at that point will be a non-SUT model to keep the bias guarantee intact.

## Update (2026-05-29): escalated to a judged band

The mandatory matcher spot-check (the validation gated above) failed: 26 of 63 v0
hallucinations (41%) were false negatives where a genuine same-item pair scored just
under the single 0.80 cutoff and was double-counted as a hallucination plus a detection
miss. Full evidence in `docs/v0-matcher-validation.md`.

We took the escalation pre-registered above rather than re-tuning the single cutoff,
because any single threshold is brittle: we cannot predict the lowest cosine a genuinely
equivalent pair will take on future transcripts, so re-tuning is a cat-and-mouse game.
The matcher now uses a **judged band**:

- cosine **>= 0.80**: auto-accept (same item; the judge would only confirm the obvious).
- cosine **< 0.50**: auto-reject (obviously unrelated; not worth a judge call).
- **0.50 <= cosine < 0.80**: an LLM judge decides "same underlying action item?".

`DEFAULT_THRESHOLD = 0.80` is the ceiling and `DEFAULT_JUDGE_FLOOR = 0.50` the floor in
`evals/matcher.py`; the judge lives in `evals/judge.py`. The band edges sit in the empty
regions of the assigned-pair cosine distribution (nothing is assigned below 0.60 in v0),
so the only genuinely ambiguous region is delegated to semantics, not to a number. See
the validation doc for why this is not just two thresholds instead of one.

**Judge model:** Claude Sonnet 4.6 (`MATCHER_JUDGE_MODEL`, overridable). It is a non-SUT
model, preserving the self-preference guarantee above. No SUT model judges its own output.

**Determinism caveat:** scoring is no longer purely deterministic. The judge runs at
temperature 0 and every verdict is cached on `(model, gt_label, agent_label)` and
persisted to `data/judge_cache.json`, so re-scores are stable and never re-pay for a pair
already seen. The cache makes the published numbers reproducible without re-calling the
judge.

**Cost:** bounded. Only band pairs reach the judge and the cache dedups them; the v0
re-score was 10 unique judge calls. The cost table line is updated from `$0`.
