# Embedding-based matching with Hungarian algorithm

Flattened detection (see ADR-001) requires pairing ground-truth items with agent output items before scoring. We use `sentence-transformers` embeddings to compute pairwise cosine similarity, then the Hungarian algorithm to find the optimal one-to-one pairing above a 0.8 cosine-similarity threshold. This is deterministic, free, and fast. The known weakness -- embeddings missing nuance like negation ("buy milk" vs "don't buy milk") -- is handled separately by the schema's `negated: bool` flag, which the agent populates directly.

### What gets embedded

The embedding input is **just the natural-language label** of each item -- `description` for `TodoItem` and `Reminder`, `title` for `CalendarEvent`. Type tokens (`"todo:"`, `"event:"`), dates, assignees, and attendees are deliberately **not** included in the embedded string. Three reasons:

1. **Type-agnostic by design.** Tier 1 (detection) is intentionally flattened across todos/reminders/events; Tier 2 (type accuracy) scores the type separately. If we put type info into the embedded string, the matcher would learn to refuse to pair a `Todo("call dentist")` with a `CalendarEvent("call dentist")` even though those should match for detection purposes and *fail* at Tier 2.
2. **Date and people fields are scored at Tier 3.** Mixing them into the matching signal would conflate detection with field accuracy, which is exactly the double-penalty problem ADR-001 set out to fix.
3. **The label carries 95%+ of the semantic signal.** Adding more text to short labels tends to dilute the cosine distance rather than sharpen it.

The matcher itself ignores type information, but the scorer needs to recover it after matching. The implementation flattens to tuples like `(embedded_text, item_type, original_object)` so Tier 2/3 can read the type and full object back off the matched pair.

This choice also eliminates self-preference bias from the core metrics: by using deterministic scoring throughout (embeddings for matching, field comparison for everything downstream), no LLM-as-judge is invoked during evaluation. If the manual spot-check shows the matcher is wrong on more than 5% of cases, we will escalate to a hybrid approach (embeddings narrow to top-K candidates, an LLM judges among those) -- and any LLM judge introduced at that point will be a non-SUT model to keep the bias guarantee intact.
