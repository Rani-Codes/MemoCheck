"""
Matcher (NOT YET IMPLEMENTED).

This file is a design stub for the embedding + Hungarian matcher described
in docs/adr/002-embedding-based-matching.md. No callable code lives here yet.

Design notes for the implementer:

- Flatten todos + reminders + events from both ground truth and agent output
  into a single pool of items per side. Notes are intentionally excluded
  (see CLAUDE.md > Metrics > "Not scored in v0").
- Each flattened item must carry its type and a back-pointer to the original
  object so Tier 2 (type accuracy) and Tier 3 (date/attribution/negation) can
  read them back off the matched pair. Suggested tuple shape:
      (embedded_text, item_type, original_object)
- The string fed to the embedder is JUST the natural-language label
  (description for TodoItem/Reminder, title for CalendarEvent). Type tokens,
  dates, and people are NOT embedded -- ADR-002 explains why.
- Cosine similarity + Hungarian algorithm, with a 0.8 threshold below which
  no pairing is allowed (those items remain unmatched and count toward
  Detection / Hallucination on their respective sides).
"""
